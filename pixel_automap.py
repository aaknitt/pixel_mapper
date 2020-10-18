from imutils import contours, grab_contours
from skimage import metrics, measure
import numpy as np
import argparse
import imutils
import cv2
import socket   
import sys  
import json
import time
from source import DMXSource
import _thread
import matplotlib.path as pltPath
from playsound import playsound

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
universes = [U1,U2,U3,U4,U5]
totalpixels = 750                 #total number of pixels to map
cap = cv2.VideoCapture('rtsp://username:password@cam.ip.add.ress:88/videoMain')  #Foscam X1 address format - others will be different
onval = [100,100,100]             #RGB value to use when turning the pixels on for detection
outfilename = 'out' + str(round(time.time())) + '.csv'  #filename to put the output data 
#**********************************************************************************

class videosource():
	def __init__(self, source, pixels):
		self.source = source
		self.currentFrame = None
		self.polygon = None
		self.point1 = [None,None]
		self.point2 = [None,None]
		self.zscale = 1
		self.outputpoints = [[0,0,0]]*pixels
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
		ret, videosource.currentFrame = videosource.source.read()
		cv2.waitKey(1)

#Starts continuosly updating the images in a thread - if we don't do this, old images get stuck in the video buffer
_thread.start_new_thread(updateFrame,(vsource,))

time.sleep(1)

class PolygonDrawer(object):
	def __init__(self, window_name,videosource):
		self.window_name = window_name # Name for our window
		self.done = False # Flag signalling we're done
		self.current = (0, 0) # Current position, so we can draw the line-in-progress
		self.points = [] # List of points defining our polygon
		self.videosource = videosource
	def on_mouse(self, event, x, y, buttons, user_param):
		# Mouse callback that gets called for every mouse event (i.e. moving, clicking, etc.)
		if self.done: # Nothing more to do
			return
		if event == cv2.EVENT_MOUSEMOVE:
			# We want to be able to draw the line-in-progress, so update current mouse position
			self.current = (x, y)
		elif event == cv2.EVENT_LBUTTONDOWN:
			# Left click means adding a point at current position to the list of points
			print("Adding point 1 #%d with position(%d,%d)" % (len(self.points), x, y))
			self.points.append((x, y))
		elif event == cv2.EVENT_RBUTTONDOWN:
			# Right click means we're done
			print("Adding point 1 #%d with position(%d,%d)" % (len(self.points), x, y))
			self.done = True
	def run(self):
		# Let's create our working window and set a mouse callback to handle events
		cv2.namedWindow(self.window_name, flags=cv2.WINDOW_NORMAL)
		
		while(not self.done):
			# This is our drawing loop, we just continuously draw new images
			# and show them in the named window
			cv2.resizeWindow(self.window_name, 800, 600);
			#cv2.imshow(self.window_name, np.zeros(CANVAS_SIZE, np.uint8))
			cv2.imshow(self.window_name,self.videosource.currentFrame)
			cv2.waitKey(1)
			cv2.setMouseCallback(self.window_name, self.on_mouse)
			height, width, channels = self.videosource.currentFrame.shape
			CANVAS_SIZE = (height,width)
			#canvas = np.zeros(CANVAS_SIZE, np.uint8)
			if (len(self.points) > 0):
				# Draw all the current polygon segments
				cv2.polylines(self.videosource.currentFrame, np.array([self.points]), False, FINAL_LINE_COLOR, 1)
				# And  also show what the current segment would look like
				cv2.line(self.videosource.currentFrame, self.points[-1], self.current, WORKING_LINE_COLOR)
			# Update the window
			cv2.imshow(self.window_name, self.videosource.currentFrame)
			# And wait 50ms before next iteration (this will pump window messages meanwhile)
			if cv2.waitKey(50) == 27: # ESC hit
				self.done = True

		# User finised entering the polygon points, so let's make the final drawing
		#canvas = np.zeros(CANVAS_SIZE, np.uint8)
		# of a filled polygon
		if (len(self.points) > 0):
			cv2.fillPoly(self.videosource.currentFrame, np.array([self.points]), FINAL_LINE_COLOR)
		# And show it
		cv2.imshow(self.window_name, self.videosource.currentFrame)
		# Waiting for the user to press any key
		cv2.waitKey(1000)
		self.videosource.polygon = self.points
		cv2.destroyWindow(self.window_name)
		return self.videosource.currentFrame

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



#Polygon masking - turn on all pixels and allow the user to draw a polygon around them to prevent
#detecting light sources outside the area of interest
all_on()  #turn all pixels on
time.sleep(1)
pd = PolygonDrawer("Polygon1",vsource)
image = pd.run()
print("Polygon = %s" % vsource.polygon)

#function to get user input during pixel mapping
#if the image processing can't find a pixel, the user can click on its location to specify the coordinates
#alternatively, the user can click outside the polygon area of interest and the coordinates will be set to 0,0 (no pixel found)
def on_mouse( event, x, y, buttons, mystuff):
	index = mystuff[0]
	videosource = mystuff[1]
	if event == cv2.EVENT_LBUTTONDOWN:
		# Left click means adding a point at current position to the list of points
		path = pltPath.Path(videosource.polygon)
		if path.contains_point([x,y]):
			videosource.outputpoints[index] = [index,x,y]
			print("Adding point #%d with position(%d,%d)" % (index, x, y))
		else:
			videosource.outputpoints[index] = [index,0,0]
			print("Adding point #%d with position(%d,%d)" % (index,0,0))

all_off()
time.sleep(1)
cv2.namedWindow("Camera1", flags=cv2.WINDOW_NORMAL)
cv2.resizeWindow("Camera1", 800, 600);
for unum, universe in enumerate(universes):
	for index in range(0,universe.pixelcount):
		attempts = 1
		while attempts >0:
			pixelout = {}
			all_off()
			time.sleep(0.7)
			image_off = vsource.currentFrame
			print("image_off")
			cv2.imshow("Camera1",image_off)
			cv2.resizeWindow("Camera1", 800, 600);
			cv2.waitKey(500)
			universe.source.send_data(data=[0,0,0]*(index) + onval + [0,0,0]*(universe.pixelcount-index-1))
			time.sleep(0.7)
			image = vsource.currentFrame
			print("image")
			cv2.imshow("Camera1",image)
			cv2.waitKey(500)
			####MASK OUT THE PORTIONS OF THE IMAGES WE DON'T CARE ABOUT###########
			height, width, channels = image_off.shape
			canvas = np.zeros((height,width), np.uint8)
			polymask = cv2.fillPoly(canvas, np.array([vsource.polygon]), [255,255,255])
			masked_image_off = cv2.bitwise_and(image_off,image_off, mask = polymask)
			masked_image = cv2.bitwise_and(image,image, mask = polymask)
			#######################IMAGE DIFFERENCE###############################
			#https://www.pyimagesearch.com/2017/06/19/image-difference-with-opencv-and-python/
			gray = cv2.cvtColor(masked_image, cv2.COLOR_BGR2GRAY)
			gray_off = cv2.cvtColor(masked_image_off, cv2.COLOR_BGR2GRAY)
			# compute the Structural Similarity Index (SSIM) between the two
			# images, ensuring that the difference image is returned
			#(score, diff) = measure.compare_ssim(gray, gray_off, full=True)
			(score, diff) = metrics.structural_similarity(gray, gray_off, full=True)
			diff = (diff * 255).astype("uint8")
			print("SSIM: {}".format(score))
			# threshold the difference image, followed by finding contours to
			# obtain the regions of the two input images that differ
			thresh = cv2.threshold(diff, 0, 255,cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
			cnts = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
			cnts = grab_contours(cnts)
			diff_mask = thresh
			diff_masked_gray = cv2.bitwise_and(gray, gray, mask = diff_mask)
			blurred = cv2.GaussianBlur(diff_masked_gray, (11, 11), 0)
			thresh2 = cv2.threshold(blurred, 150, 255, cv2.THRESH_BINARY)[1]
			# perform a series of erosions and dilations to remove
			# any small blobs of noise from the thresholded image
			#thresh = cv2.erode(thresh, None, iterations=2)
			#thresh = cv2.dilate(thresh, None, iterations=4)
			# perform a connected component analysis on the thresholded
			# image, then initialize a mask to store only the "large"
			# components
			labels = measure.label(thresh2, connectivity=2, background=0)
			mask = np.zeros(thresh2.shape, dtype="uint8")
			# loop over the unique components
			for label in np.unique(labels):
				# if this is the background label, ignore it
				if label == 0:
					continue
				# otherwise, construct the label mask and count the
				# number of pixels 
				labelMask = np.zeros(thresh2.shape, dtype="uint8")
				labelMask[labels == label] = 255
				numPixels = cv2.countNonZero(labelMask)
				# if the number of pixels in the component is sufficiently
				# large, then add it to our mask of "large blobs"
				if numPixels > 50:
					mask = cv2.add(mask, labelMask)
			# find the contours in the mask, then sort them from left to
			# right
			cnts = cv2.findContours(mask.copy(), cv2.RETR_EXTERNAL,
				cv2.CHAIN_APPROX_SIMPLE)
			print(cnts)
			cnts = cnts[0] if (imutils.is_cv2() or imutils.is_cv4()) else cnts[1]
			if len(cnts) > 0:
				cnts = contours.sort_contours(cnts)[0]
				# loop over the contours
				for (i, c) in enumerate(cnts):
					# draw the bright spot on the image
					(x, y, w, h) = cv2.boundingRect(c)
					((cX, cY), radius) = cv2.minEnclosingCircle(c)
					cv2.circle(image, (int(cX), int(cY)), int(radius),
						(0, 0, 255), 3)
					cv2.putText(image, str(cX) + " " + str(cY), (x, y - 15),
						cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 2)
					# show the output image
					cv2.imshow("Camera1", image)
					cv2.waitKey(1)
				if len(cnts)== 1:
					attempts = 0
					print("Pixel " + str(index) + " coordinates: [" + str(x) + "," + str(y) + "]")
					vsource.outputpoints[unum*170+index] = [unum*170+index,cX,cY]
				else:
					print("too many bright spots, trying again!")
					attempts = attempts + 1
					cv2.imshow("Camera1",image)
					cv2.waitKey(5)
			else:
				print("No bright spots found")
				attempts = attempts + 1
			if attempts >= 2:
				print('too many points attempts - click on the pixel to locate or click outside of polygon to skip') 
				playsound('alert.wav')
				cv2.imshow("Camera1", image)
				cv2.setMouseCallback("Camera1",on_mouse,[unum*170+index,vsource])
				done = 0
				while done == 0:
					cv2.waitKey(50)
					if vsource.outputpoints[unum*170+index] != [0,0,0]:
						done = 1
					else:
						done = 0
				attempts = 0
		with open('data1.txt', 'a') as outfile:
			outfile.write(str(unum*170+index) + ',' + str(vsource.outputpoints[unum*170+index][1]) + ',' + str(vsource.outputpoints[unum*170+index][2]) + "\n")
all_off()

with open(outfilename, 'w') as outfile:
	#json.dump([sorted_by_pixel_x, sorted_by_pixel_y], outfile)
	json.dump(videosource.outputpoints, outfile)
