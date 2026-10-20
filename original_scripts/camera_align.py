import cv2
import _thread
import time

camera_resolution = [1920,1080]   #resolution (in pixels) of the camera [Horizontal, Vertical]
#cap = cv2.VideoCapture('rtsp://username:password@cam.ip.add.ress:88/videoMain')  #Foscam X1 format address - others will be different

def returnCameraIndexes():
	# checks the first 10 indexes.
	index = 0
	arr = []
	i = 10
	while i > 0:
		cap = cv2.VideoCapture(index)
		if cap.read()[0]:
			arr.append(index)
			cap.release()
		index += 1
		i -= 1
	return arr

#print(returnCameraIndexes())
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, camera_resolution[0])
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, camera_resolution[1])

class videosource():
	def __init__(self, source):
		self.source = source
		self.retval = False
		self.currentFrame = None
		self.polygon = None
		self.point1 = [None,None]
		self.point2 = [None,None]
		self.zscale = 1
		self.resolution = []
		self.fov = []

vsource = videosource(cap)
vsource.resolution = camera_resolution

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
#display alignment overlays until the user hits ESK key
done = False
yellow_line_location = round(vsource.resolution[0]/3)
while done == False:
	image = vsource.currentFrame
	#ret, image = cap.read()
	cv2.namedWindow("Alignment", flags=cv2.WINDOW_NORMAL)
	#overlay a vertical blue line at the centerpoint of the picture
	image = cv2.line(image,(round(vsource.resolution[0]/2),0),(round(vsource.resolution[0]/2),round(vsource.resolution[1])),(255,0,0),5)
	#overlay a horiztonal blue line a the centerpoint of the picture
	image = cv2.line(image,(0,round(vsource.resolution[1]/2)),(vsource.resolution[0],round(vsource.resolution[1]/2)),(255,0,0),5)
	#overlay two yellow vertical lines equidistant from the center
	image = cv2.line(image,(round(vsource.resolution[0]/2+yellow_line_location),0),(round(vsource.resolution[0]/2+yellow_line_location),vsource.resolution[1]),(0,255,0),5)
	image = cv2.line(image,(round(vsource.resolution[0]/2-yellow_line_location),0),(round(vsource.resolution[0]/2-yellow_line_location),vsource.resolution[1]),(0,255,0),5)
	cv2.imshow("Alignment",image)
	cv2.resizeWindow("Alignment", 800, 450);
	key = cv2.waitKeyEx(50)
	#if key != -1:
	#	print(key)
	if  key == 27: # ESC hit
		done = True
	elif key == 2555904:  #right arrow
		yellow_line_location = min(yellow_line_location + 5,vsource.resolution[0]/2-5)
		print(yellow_line_location)
	elif key == 2424832:  #left arrow
		yellow_line_location = max(yellow_line_location - 5,5)
		print(yellow_line_location)
		
cv2.destroyWindow("Alignment")