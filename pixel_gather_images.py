import argparse
import imutils
import cv2
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
U5 = Universe(DMXSource(universe=2004),60)
universes = [U3]
totalpixels = 190                 #total number of pixels to map
#cap = cv2.VideoCapture('rtsp://user:password@ip.addr.of.cam:88/videoMain')  #Foscam X1 address format - others will be different
camera_resolution = [1920,1080]   #resolution (in pixels) of the camera [Horizontal, Vertical]
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, camera_resolution[0])
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, camera_resolution[1])
onval = [255,255,255]             #RGB value to use when turning the pixels on for detection
foldername = 'images_' + str(round(time.time()))  #folder to put the output images 
#**********************************************************************************

class videosource():
	def __init__(self, source, pixels):
		self.source = source
		self.currentFrame = None
		self.retval = False
		self.polygon = None
		self.point1 = [None,None]
		self.point2 = [None,None]
		self.zscale = 1
		self.outputpoints = [[-1,0,0]]*pixels
		self.resolution = []
		self.fov = []

vsource = videosource(cap,totalpixels)

CANVAS_SIZE = (600,800)
FINAL_LINE_COLOR = (255, 255, 255)
WORKING_LINE_COLOR = (127, 127, 127)

#Function to continuoulsy get video data and update our videosource with the latest frame
#this is needed to keep the frame buffer fresh with new data.  This function
#will be running in its own thread that gets started below
def updateFrame(videosource):
	while(True):
		videosource.retval, videosource.currentFrame = videosource.source.read()
		cv2.waitKey(1)

#Starts continuosly updating the images in a thread - if we don't do this, old images get stuck in the video buffer
_thread.start_new_thread(updateFrame,(vsource,))
while vsource.retval == False:
	print("waiting for video")
	time.sleep(1)

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
image = vsource.currentFrame
cv2.imwrite(foldername + '/all_on.png',image)
cv2.namedWindow("Camera1", flags=cv2.WINDOW_NORMAL)
cv2.imshow("Camera1",image)
cv2.resizeWindow("Camera1", 800, 600);
cv2.waitKey(500)
counter = 0
for unum, universe in enumerate(universes):
	for index in range(0,universe.pixelcount):
		universe.source.send_data(data=[0,0,0]*(index) + onval + [0,0,0]*(universe.pixelcount-index-1))
		time.sleep(2)
		image = vsource.currentFrame
		cv2.imwrite(foldername + '/' + str(counter) + '.png',image)
		print("Wrote image for pixel " + str(counter))
		cv2.imshow("Camera1",image)
		cv2.waitKey(100)
		counter = counter + 1
all_off()

