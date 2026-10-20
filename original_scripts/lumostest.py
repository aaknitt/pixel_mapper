#import argparse
#import imutils
import socket 
import sys  
import time
from lumos import DMXSource
import _thread
import os

class Universe:
	def __init__(self,source,channelcount):
		self.source = source
		self.pixelcount = int(channelcount/3)

#EDIT THESE LINES AS NEEDED******************************************************
#Configure the Universes to send to when controlling the pixels
#format is as follows:
#U1 = Universe(DMXSource(universe=UNIVERSE NUMBER),NUMBER OF CHANNELS IN THE UNIVERSE)  #for RGB pixels, there are three channels per pixel
U1 = Universe(DMXSource(universe=2000),510)
U2 = Universe(DMXSource(universe=2001),510)
U3 = Universe(DMXSource(universe=2002),510)
U4 = Universe(DMXSource(universe=2003),510)
U5 = Universe(DMXSource(universe=2004),210)
universes = [U1,U2,U3,U4,U5]
totalpixels = 750                 #total number of pixels to map
#cap = cv2.VideoCapture('rtsp://user:password@ip.addr.of.cam:88/videoMain')  #Foscam X1 address format - others will be different
camera_resolution = [1920,1080]   #resolution (in pixels) of the camera [Horizontal, Vertical]

onval = [255,255,255]             #RGB value to use when turning the pixels on for detection
foldername = 'images_' + str(round(time.time()))  #folder to put the output images 
#**********************************************************************************

CANVAS_SIZE = (600,800)
FINAL_LINE_COLOR = (255, 255, 255)
WORKING_LINE_COLOR = (127, 127, 127)

output = []
def all_off():
	#shut all pixels off
	for universe in universes:
		universe.source.send_data(data=[0,0,0]*universe.pixelcount)
def everyother():
	#turn every other pixel on - for testing
	for universe in universes:
		universe.source.send_data(data=onval*universe.pixelcount)
		counter = 0
		for i,element in enumerate(data):
			if counter == 3 or counter == 4 or counter == 5:
				data[i] = 0
			counter = counter + 1
			if counter > 5:
				counter = 0
def all_on():
	#turn all pixels on white
	for universe in universes:
		universe.source.send_data(data=onval*universe.pixelcount)

os.makedirs(foldername)
all_off()
time.sleep(1)
all_on()
time.sleep(2)
all_off()
time.sleep(1)
all_off()
counter = 0
for unum, universe in enumerate(universes):
	for index in range(0,universe.pixelcount):
		universe.source.send_data(data=[0,0,0]*(index) + onval + [0,0,0]*(universe.pixelcount-index-1))
		print("sending " + str(counter))
		time.sleep(2)
		counter = counter + 1
all_off()

