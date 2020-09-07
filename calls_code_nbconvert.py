#!/usr/bin/env python
# coding: utf-8

# In[1]:


import pandas as pd
import datetime
import seaborn as sbn
import matplotlib.pyplot as plt
import geopandas as gpd
import folium
#event_location =
#event_date =


# 
# ## The police dataset - onboarding and cleaning up
# The SPD publishes a .csv of virtually all 911 calls (originating from both within and without the SPD), with the following columns:
# * CAD event number
# * Event Clearance Description
# * Call Type
# * Priority
# * Initial Call Type
# * Final Call Type
# * Original Time Queued
# * Arrived Time
# * Precinct
# * Sector
# * Beat
# 
# For development, I'm using a download of the 911 calls. (For actual implementation, it is possible to download new data on demand as the tool is run, determining if the most recent entry date is within the date range used and downloading all entries  after that date and all non-redundant entries from that date.)
# 
# I'm dropping times from the dataframe as they're unneeded and converting the date strings to datetime. This conversion takes a non-trivial amount of time, hence the future plan to download only new data, convert, and add to the dataframe.
# 

# In[2]:


call_data = pd.read_csv('Call_Data.csv')

# Getting headers for list above
call_data_heads = call_data.head()
call_data_heads

# What are the unique call types present in the dataframe?
call_CT_entries = call_data.loc[:,['Call Type']]
call_CT_entries.drop_duplicates(inplace = True)
call_CT_entries.sort_values(by = ['Call Type'])
call_CT_entries
# One of the reasons I abandoned the police report data was the amount of noise in the system - more reports are generated when more officer-hours are spent in a given beat. And I know that there are times when specific places are very heavily patrolled - see: cop towers in mall parking lot during the holidays. For that reason, I'm going to create a "Call Source" column with values "external" (TELEPHONE OTHER, NOT 911; 911; ALARM CALL (NOT POLICE ALARM); POLICE (VARDA) ALARM; IN PERSON COMPLAINT; and TEXT MESSAGE), "internal" (ONVIEW, PROACTIVE (OFFICER INITIATED), and SCHEDULED EVENT (RECURRING)), and "error" (HISTORY CALL (RETRO) and FK ERROR).
# 
# The primary data for examining changes in crime will be external calls. These can be compared to internal calls to see if my hypothesis is correct that most of the noise in the system is due to internal calls.

# In[3]:


# Slicing out a test dataset for testing approaches on; closer to middle of df to assure it's "actual" not historical
call_data_test = call_data.iloc[2000000:2000100,:]


# In[4]:


external_call_types_list = ["TELEPHONE OTHER, not 911", "911", "ALARM CALL (NOT POLICE ALARM)", "POLICE (VARDA ALARM)", "IN PERSON COMPLAINT", "TEXT MESSAGE"]
internal_call_types_list = ["ONVIEW", "PROACTIVE (OFFICER INITIATED)", "SCHEDULED EVENT (RECURRING)"]
def callSource(x):
    if x in internal_call_types_list:
        return "Internal"
    elif x in external_call_types_list:
        return "External"
    else:
        return "Other"

call_data_modified = call_data
# Appending the "Call Source" column to the dataframe based on the entries in "Call Type"
call_data_modified["Call Source"] = [callSource(entry) for entry in call_data.iloc[:,2]]
# Saving my work because the previous iteration-based attempt took half of forever
call_data_modified.to_csv('911 reports modified.txt', index=False, sep='\t')


# There are too many final and initial call types (418 and 315, respectively) for the approach of binning crimes by type, as done with the police reports, to be a good investment of energy, at least without some evidence that this exercise will actually be useful.
# 
# Initial attempt to apply the previously-developed code from SPD-reports before-after shows that "Original Time Queued" is stored in the dataframe as a string. Thankfully, the format seems to be consistent?
# MM/DD/YYYY HH:MM:SS AP
# %m/%d/%Y  %l:%M:%S %p

# In[5]:


import datetime

# Modified from JournalDev python string to datatime - strptime()
def timeConversion(x):
    try:
        # Converting string of set format to date only
        return datetime.datetime.strptime(x, '%m/%d/%Y %H:%M:%S %p').date()
    except ValueError as ve:
        try:
            # Converting with a slower function that can deal with variations in format to a certain extent
            pd.to_datetime(x, dayfirst = False, yearfirst = False, infer_datetime_format = True)
        except ValueError as ve:
            print('ValueError Raised:', ve)


    
# Using timeConversion(x) to update all the entries for "Original Time Queued" in call_data
call_data.iloc[:,6] = call_data.iloc[:,6].map(timeConversion)


# ## Changes in beats
# One of the complications of using this dataset is that the most precise location is by beat, and beat boundaries have changed repeatedly over the years.
# 
# Crime data is noisy, particularly violent crime, since the numbers are relatively low. At a guess, a 90 day window is probably the minimum span where the signal-to-noise ratio is acceptable. Given that there are seasonal variations in all kinds of human data (and things like noise complaints are probably more prevalent in the summer), the default will be to compare the year prior to the given date and the year following the given date.
# 
# There have also been small changes to how precincts and sectors have been drawn, but precinct-level changes seem to be limited to the East and West Precincts for 2015.
# 
# Per the SPD Beats data, https://data.seattle.gov/Public-Safety/Seattle-Police-Department-Beats/nnxn-434b, beats have been changed at 2008, 2015, and 2018. For the moment, comparisons that cross one of these date boundaries will throw a warning that data may be flawed as beat boundaries may have changed; with more time to research the history, analyses can be allowed or disallowed based on whether or not the boundaries of the beat in question changed at the particular time.

# In[6]:


window = 90
event_date = datetime.date(2015, 4, 5)
event_location = "B2"
beat_changes = [datetime.date(2008, 1, 1), datetime.date(2015, 1, 1), datetime.date(2018, 1, 1)]
for entry in beat_changes:
    if abs(event_date - entry) < datetime.timedelta(days = window):
        print("CAUTION: Beats have changed during the window used; proceed with caution or compare by sector/precinct")
if event_date - datetime.timedelta(days = 90) < datetime.date(2009, 6, 2):
    print("First entry in call_data is 6 June 2009; adjust window or choose another event date.")


# From the parent call_data set, a subset is constructed consisting of incidents within the query window of the date in question with sources "Internal" or "External".

# In[7]:


start = event_date - datetime.timedelta(days = window)
end = event_date + datetime.timedelta(days = window)
within_window = call_data.loc[(call_data["Original Time Queued"] > start) & (call_data["Original Time Queued"] < end), ["CAD Event Number", "Call Source", "Original Time Queued", "Precinct", "Sector", "Beat"]].copy()
within_window


# ## Getting rates
# 
# From the subset, we can get a count of crimes of each type, before and after the date in question, within and without the area in question.
# 
# The simplest comparison is to look at the percentage change in crime from the before to the after, comparing the within-beat change to the change for all other beats across the same time period.
# 
# Comparing crime from area to area is often done on #/standard population unit level, but the census data I found isn't easily applied to beats, and census data is going to be a bit squiffy when it comes to actual occupancy in areas not zoned for residences (i.e. lots of people work there during the day and a few people live there in their cars at night).

# In[28]:


precinct = ["EAST", "NORTH", "SOUTH", "SOUTHWEST", "WEST", "UNKNOWN"]
sector = ["B", "C", "D", "E", "F", "G", "J", "K", "L", "M", "N", "O", "Q", "R", "S", "U", "W"]
beat = ["B1", "B2", "B3", "C1", "C2", "C3", "D1", "D2", "D3", "E1", "E2", "E3", "F1", "F2", "F3", "G1", "G2", "G3", "J1", "J2", "J3", "K1", "K2", "K3", "L1", "L2", "L3", "M1", "M2", "M3", "N1", "N2", "N3", "O1", "O2", "O3", "Q1", "Q2", "Q3", "R1", "R2", "R3", "S1", "S2", "S3", "U1", "U2", "U3", "W1", "W2", "W3"]

#Using sum to get count of entries that fit given parameters by location (geo_flag)
#geo_flag manually set to beat here, but future plan is to allow user to choose at onset, with beat being default
geo_flag = beat
all_before = [sum((within_window["Original Time Queued"] < event_date) & (within_window["Beat"] == entry)) for entry in geo_flag]
all_after = [sum((within_window["Original Time Queued"] >= event_date) & (within_window["Beat"] == entry)) for entry in geo_flag]
total = [(after-before)/(max(before, 1))*100 for before, after in zip(all_before, all_after)]

int_before = [sum((within_window["Original Time Queued"] < event_date) & (within_window["Beat"] == entry) & (within_window["Call Source"] == "Internal")) for entry in geo_flag]
int_after = [sum((within_window["Original Time Queued"] >= event_date) & (within_window["Beat"] == entry) & (within_window["Call Source"] == "Internal")) for entry in geo_flag]
internal = [(after-before)/(max(before, 1))*100 for before, after in zip(int_before, int_after)]

ext_before = [sum((within_window["Original Time Queued"] < event_date) & (within_window["Beat"] == entry) & (within_window["Call Source"] == "External")) for entry in geo_flag]
ext_after = [sum((within_window["Original Time Queued"] >= event_date) & (within_window["Beat"] == entry) & (within_window["Call Source"] == "External")) for entry in geo_flag]
external = [(after-before)/(max(before, 1))*100 for before, after in zip(ext_before, ext_after)]

oth_before = [sum((within_window["Original Time Queued"] < event_date) & (within_window["Beat"] == entry) & (within_window["Call Source"] == "Other")) for entry in geo_flag]
oth_after = [sum((within_window["Original Time Queued"] >= event_date) & (within_window["Beat"] == entry) & (within_window["Call Source"] == "Other")) for entry in geo_flag]
other = [(after-before)/(max(before, 1))*100 for before, after in zip(oth_before, oth_after)]


# In[29]:


# Combining the lists of percentages into a single dataframe
percentages = pd.DataFrame({"beat": beat, "total": total, "internal": internal, "external": external, "other": other})
percentages


# Where's a particular beat relative to the whole, then? 

# In[273]:


# Finding index for the event_location; gets a little arcane because .index returns a int64 type
event_location_index = percentages.index[percentages['beat'] == event_location].to_list()[0]
# Slice out beat of interest
beat_of_interest = percentages.iloc[event_location_index, 1:]
# beat_of_interest transposed,shoved into a dataframe, & index reset so it can be used w/ dataframe.plot.scatter
beat_of_interest_frame = beat_of_interest.transpose().to_frame().reset_index()
# Since beat_of_interest_frame is essentially a vector with labels for index, percents will always be in column 1
beat_of_interest_frame.plot.scatter(x = "index", y = 1)
# Initialize data_plot with box plot of percentage change for all beats
data_plot = sbn.boxplot(data = percentages)
# Scatter plot of only beat of interest on top of boxplot
#beat_of_interest_frame.plot.scatter(x = "index", y = event_location, ax = data_plot, color = "black")
data_plot.set_xlabel("Call Source")
data_plot.set_ylabel("Percentage change")
data_plot.set_title("Percentage change in calls for " + str(window) + " days after versus before " + str(event_date) + 
                    "\nfor all beats (boxplot) and " + str(event_location) + " (black dot)")


# And let's make sure we're actually giving a statistical (rather than "by eyeball") measure of whether our not the values for the given beat are significantly different from the rest of the beats. We can look at both the external calls and the totality of calls.

# In[279]:


# Determining how far the beat of interest is from the mean, in terms of the standard deviation.
# Because this is a population standard deviation, the degrees of freedom is equal to the number of datapoints, not n-1
beat_percentage_distance = (percentages.loc[event_location_index, 'external'] - percentages['external'].mean())/ percentages['external'].std(ddof = 0)
if beat_percentage_distance < 0:
    direction = 'decreased'
else:
    direction = 'increased'
print('The change in calls for ' + event_location + ' is ' + str(round(percentages.loc[event_location_index, 'external'], 2)) + '%,  or ' + str(round(beat_percentage_distance, 2)) + ' standard deviations from the mean.')
if abs(beat_percentage_distance) <= 2.0:
    print('The event is unlikely to have significantly impacted calls to the police.')
else:
    print('The event may have significantly ' + direction + ' calls to the police.')


# What about visualization by location? After all, I'm always seeing shaded maps in /r/dataisbeautiful, so let's see how difficult it is to set that up. (Spoiler: a choropleth is pretty straightforward once you figure out how, but if you're working with map areas that aren't labeled on the map tiles, it's a bit trickier.)
# 
# Let's start by using geopandas. A necessary future improvement will be to have the program automatically pull the appropriate beat, but first I need to get to the basic visualization.
# 
# One critical issue is that the order of beats in the geodataframe doesn't match the order of beats I've been working with, and I have no reason to believe that beat order will be consistent across the shapefiles. For that reason, it makes sense to append the percentage change values to the geodataframe by calling the appropriate value from the percentage change dataframe. This kind of iteration is decidedly slow on dataframes in general, but we're also working with <100 entries, so it's not a real problem compared with reading in the data and assembling the within_window dataframe.

# In[222]:


# Initializing geodataframe using shapefile
spd_beats_temp = gpd.read_file('Seattle_Police_Beats_2018-present.shp')
# Getting geodataframe into the same order as beat
spd_beats_temp.sort_values(by = "beat", inplace = True)
# Slicing out the "no beat" line
spd_beats = spd_beats_temp.iloc[1:, :]
spd_beats.to_file("beats2018-present.geojson", driver = "GeoJSON")


# The beat maps are static, not dynamic, so there's no need to keep repeating the pull-edit-create process over and over. Instead, let's export the geodataframe to a file with a clear name, and do this for all four beat maps. Then, when this project is turned into a proper program, it can pull the beat map as appropriate.
# Repeating whole process for pre-2008 beats map
spd_beats_pre_08 = gpd.read_file('Seattle_Police_Beats_Pre-2008.shp')
spd_beats_pre_08.sort_values(by = "beat", inplace = True)
spd_beats_pre_08 = spd_beats_pre_08.iloc[1:, :]
spd_beats_pre_08.to_file("beatsPre2008.geojson", driver = "GeoJSON")

# Repeating whole process for 2008-2015 beats map
spd_beats_08_15 = gpd.read_file('Seattle_Police_Beats_2008-2015.shp')
spd_beats_08_15.sort_values(by = "beat", inplace = True)
spd_beats_08_15 = spd_beats_08_15.iloc[1:, :]
spd_beats_08_15.to_file("beats2008-2015.geojson", driver = "GeoJSON")

# Repeating whole process for 2015-2017 beats map
spd_beats_15_17 = gpd.read_file('Seattle_Police_Beats_2015-2017.shp')
spd_beats_15_17.sort_values(by = "beat", inplace = True)
spd_beats_15_17 = spd_beats_15_17.iloc[1:, :]
spd_beats_15_17.to_file("beats2015-2017.geojson", driver = "GeoJSON")# Getting representative point (approx center) per https://stackoverflow.com/a/38902492/2880512
spd_beats['label_point'] = spd_beats['geometry'].apply(lambda x: x.representative_point().coords)
# Converting shapely point object into single entries
spd_beats['label_lat'] = [point[0][1] for point in spd_beats['label_point']]
spd_beats['label_lon'] = [point[0][0] for point in spd_beats['label_point']]
# Dropping label_point so dataframe can be exported.
spd_beats.drop(columns = 'label_point', inplace = True)
# Manually dropping a marker onto the map to confirm that representative_point worked reasonably
#folium.Marker((47.661, -122.360),
#              folium.Tooltip(spd_beats.iloc[1, 2],)).add_to(mapviz)# Repeating process including saving to GeoJSON so that this part doesn't need to be wrapped into the function
spd_beats_pre_08['label_point'] = spd_beats_pre_08['geometry'].apply(lambda x: x.representative_point().coords)
spd_beats_pre_08['label_lat'] = [point[0][1] for point in spd_beats_pre_08['label_point']]
spd_beats_pre_08['label_lon'] = [point[0][0] for point in spd_beats_pre_08['label_point']]
spd_beats_pre_08.drop(columns = 'label_point', inplace = True)
spd_beats_pre_08.to_file("beatsPre2008.geojson", driver = "GeoJSON")

spd_beats_08_15['label_point'] = spd_beats_08_15['geometry'].apply(lambda x: x.representative_point().coords)
spd_beats_08_15['label_lat'] = [point[0][1] for point in spd_beats_08_15['label_point']]
spd_beats_08_15['label_lon'] = [point[0][0] for point in spd_beats_08_15['label_point']]
spd_beats_08_15.drop(columns = 'label_point', inplace = True)
spd_beats_08_15.to_file("beats2008-2015.geojson", driver = "GeoJSON")

spd_beats_15_17['label_point'] = spd_beats_15_17['geometry'].apply(lambda x: x.representative_point().coords)
spd_beats_15_17['label_lat'] = [point[0][1] for point in spd_beats_15_17['label_point']]
spd_beats_15_17['label_lon'] = [point[0][0] for point in spd_beats_15_17['label_point']]
spd_beats_15_17.drop(columns = 'label_point', inplace = True)
spd_beats_15_17.to_file("beats2015-2017.geojson", driver = "GeoJSON")

# In[191]:


# Code adapted from https://www.nagarajbhat.com/post/folium-visualization/
# Map centered on Seattle and zoomed appropriately for beats map
mapviz = folium.Map([47.6, -122.3], 
                    zoom_start = 11)
# Creating choropleth layer; note that since there are an even number of bins, the middle of the legend is the median. 
choropleth = folium.Choropleth(geo_data = spd_beats,
                              name = 'percentages shading',
                              data = percentages,
                              columns = ["beat", "external"],
                              key_on = 'properties.beat',
                               bins = 8,
                              fill_color = 'PuBuGn',
                               nan_fill_color = '#ffffff',
                               nan_fill_opacity = 0.1,
                              legend = 'Change in external calls compared to before event (percentage)',
                              ).add_to(mapviz)
folium.LayerControl(collapsed = True).add_to(mapviz)

# Adapting DivIcon code from https://github.com/python-visualization/folium/issues/340#issuecomment-179673692
from folium.features import DivIcon

# Nope; something is hinky with the string literal line
for index in spd_beats:
    folium.map.Marker([spd_beats.iloc[index, 7], 
                   spd_beats.iloc[index, 8]],
                 icon = DivIcon(
                     html = '<div style = "font size: 16 pt, color: black, text-align: center">{spd_beats.iloc[index, 2]}</div>')).add_to(mapviz)# Nope; dummy/index is an object and can't be forced to int. RTM.
for index in spd_beats:
    dummy = index
    folium.map.Marker([spd_beats.iloc[dummy, 7], 
                   spd_beats.iloc[dummy, 8]],
                 icon = DivIcon(
                     html = spd_beats.iloc[dummy, 2],
                     style = "font size: 16 pt, color: black, text-align: center")).add_to(mapviz)# Also nope; style arg to DivIcon not accepted.
# Adapted from https://nbviewer.jupyter.org/gist/BibMartin/ec2a96034043a7d5035b
for x in range(0, len(spd_beats)):
    folium.map.Marker([spd_beats.loc[x, 7], 
                   spd_beats.loc[x, 8]],
                 icon = DivIcon(
                     html = spd_beats.iloc[x, 2],
                     style = "font size: 16 pt, color: black, text-align: center")).add_to(mapviz)
# In[233]:


# Using folium's DivIcon builtin to create beat labels en masse
for x in range(0, len(spd_beats)):
    folium.map.Marker([spd_beats.iloc[x, 7], 
                   spd_beats.iloc[x, 8]],
                       icon = DivIcon(
                     html = spd_beats.iloc[x, 1],
                    )).add_to(mapviz)


# In[193]:


mapviz


# It appears that calls originating outside SPD may be less variable than internal calls; if this were a tool I was building purely for fun, rather than as a thing to talk about at the interview, this is the point where I'd work on turning it into a function so that I could run a bunch of random dates to determine
# 1. When plotting standard deviation of data against window size, is there an inflection point in the slope? This would help inform minimum window size.
# 2. Is the "External" subset consistently show smaller variance than the "Internal" subset? If so, this strengthens the case for consistently using "External", at least once non-issue calls are stripped from the dataframe.
# 
# However, I want the proto-dashboard I show people to be as interesting as possible, and one of the major underlying hypotheses of this project is that certain events may affect "crime" (as measured by requests for SPD assistance), but probably only specific types of crime.
# I would expect a homeless encampment moving in to result in a spike in calls for suspicious persons, drugs, and drunk & disorderly. It might also result in an increase in property crime. I would not expect it to affect traffic calls, and I hope it won't affect violent crime - that's probably the biggest and most important question I'm trying to answer here.
# Similarly, I would expect long-term construction that closes roads to affect traffic reports but little else.
# 
# In order to do this hypothesis-testing, I need to be able to do something with "Event Clearance Description", "Initial Call Type", and "Final Call Type". Let's dig in!

# In[281]:


call_ECD_entries = call_data.loc[:,['Event Clearance Description']]
call_ECD_entries.drop_duplicates(inplace = True)
#call_ECD_entries.sort_values(['Event Clearance Description'], ignore_index = True)
pd.set_option('display.max_rows', None)
type(call_ECD_entries)


# Something hinky is going on here. Not sure why, but sorting isn't happening correctly. Was going to need to strip leading whitespace and majority of punctuation anyway, so let's get to that.
