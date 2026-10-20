#Requires fswebcam installed on the Pi: sudo apt-get install fswebcam
import socket 
import sys  
import time
from lumos import DMXSource
import _thread
import os
import subprocess


class Universe:
	def __init__(self,source,channelcount):
		self.source = source
		self.pixelcount = int(channelcount/3)

#EDIT THESE LINES AS NEEDED******************************************************
#Configure the Universes to send to when controlling the pixels
#format is as follows:
#U1 = Universe(DMXSource(universe=UNIVERSE NUMBER),NUMBER OF CHANNELS IN THE UNIVERSE)  #for RGB pixels, there are three channels per pixel
#TREE
'''
U1 = Universe(DMXSource(universe=2000,unicast_ip='192.168.1.143'),510)
U2 = Universe(DMXSource(universe=2001,unicast_ip='192.168.1.143'),510)
U3 = Universe(DMXSource(universe=2002,unicast_ip='192.168.1.143'),510)
U4 = Universe(DMXSource(universe=2003,unicast_ip='192.168.1.143'),510)
U5 = Universe(DMXSource(universe=2004,unicast_ip='192.168.1.143'),210)
universes = [U1,U2,U3,U4,U5]
totalpixels = 750                 #total number of pixels to map
'''
#BUSH1
#U1 = Universe(DMXSource(universe=5000,unicast_ip='192.168.1.153'),300)
#universes = [U1]
#totalpixels = 100                 #total number of pixels to map

#BUSH2
#U1 = Universe(DMXSource(universe=5001,unicast_ip='192.168.1.153'),300)
#universes = [U1]
#totalpixels = 100                 #total number of pixels to map

#BUSH3
#U1 = Universe(DMXSource(universe=6000,unicast_ip='192.168.1.163'),450)
#universes = [U1]
#totalpixels = 150                 #total number of pixels to map

#BUSH4
U1 = Universe(DMXSource(universe=6001,unicast_ip='192.168.1.163'),450)
universes = [U1]
totalpixels = 150                 #total number of pixels to map

camera_resolution = [1920,1080]   #resolution (in pixels) of the camera [Horizontal, Vertical]
allonval = [255,255,255]          #RGB value to use when turning all pixels on for detection
onval = [255,255,255]             #RGB value to use when turning one pixel on for detection
foldername = 'images_' + str(round(time.time()))  #folder to put the output images 
#**********************************************************************************

def all_off():
	#shut all pixels off
	for universe in universes:
		universe.source.send_data(data=[0,0,0]*universe.pixelcount)

def all_on():
	#turn all pixels on white
	for universe in universes:
		universe.source.send_data(data=allonval*universe.pixelcount)

os.makedirs(foldername)
#capture a bunch of frames to let the camera auto-adjust brightness, etc.
print("turning all on")
all_on()
subprocess.run(['fswebcam', '-F','100','-r', '1920x1080', '--no-banner' ,foldername + '/adjust.png'])
all_on()
time.sleep(2)
all_on()
subprocess.run(['fswebcam','-F','10','-r', '1920x1080', '--no-banner' ,foldername + '/all_on.png'])
index = 0
time.sleep(1)
print("turning all off")
all_off()
time.sleep(1)
counter = 0
print("starting pixel by pixel")
for unum, universe in enumerate(universes):
	for index in range(0,universe.pixelcount):
		universe.source.send_data(data=[0,0,0]*(index) + onval + [0,0,0]*(universe.pixelcount-index-1))
		print("sending pixel " + str(counter))
		time.sleep(.2)
		subprocess.run(['fswebcam', '-F','10','-r', '1920x1080', '--no-banner' ,foldername + '/' + str(counter) + '.png'])
		print("Wrote image for pixel " + str(counter))
		counter = counter + 1
all_off()

