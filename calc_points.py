import json
import math
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import numpy as np
import csv
from scipy.spatial.transform import Rotation as R

#Three CSV data files containing the 2D coordinate points found from each of three camera positions
#The three camera positions form an equilateral triangle around the pixel array
#second camera position is to the right of the first position - counter-clockwise rotation
#these files are generated from running pixel_automap.py three times - one from each camera location
files = ['data/dataC1U1-5.csv','data/dataC2U1-5.csv','data/dataC3U1-5.csv']

fov = [95, 53] #field of view of the camera [degreesHorizontal,degreesVertical]
res = [1920, 1080] #resolution (in pixels) of the camera [Horizontal, Vertical]
D = 370  #distance (in any units) from the camera to the center of the triangle
xLights_output_scale_factor = 3.0  #scaling factor to reduce the size of the xLights output file to a reasonable size

data = []
for i, file in enumerate(files):
	with open(file, 'r') as f:
		my_list = [list(map(float,rec)) for rec in csv.reader(f, delimiter=',')]
		data.append(my_list)

outpoints = [[[0,0,0,0] for i in range(len(data[0]))] for i in range(3)]

#second camera is to the right of the first camera - counter-clockwise rotation
combinations = [[data[0],data[1]],[data[1],data[2]],[data[2],data[0]]]
for k, combodata in enumerate(combinations):
	for i in range(0,len(combodata[0])):
		if combodata[0][i][1] != 0 and combodata[1][i][1] != 0:  #camera 1 and camera 2 points are both valid
			C1angle = 180 - (fov[0]/2.)*(combodata[0][i][1]-res[0]/2.)/(res[0]/2.)
			C2angle = 120 - (fov[0]/2.)*(combodata[1][i][1]-res[0]/2.)/(res[0]/2.)
			C1slope = math.tan(math.radians(C1angle))
			C2slope = math.tan(math.radians(C2angle))
			C1loc = [D,0]
			C2loc = [-1*math.cos(math.radians(60))*D,math.sin(math.radians(60))*D]
			C1intercept = C1loc[1]-C1slope*C1loc[0]  #y=mx+b -> b = y-mx
			C2intercept = C2loc[1]-C2slope*C2loc[0]  #y=mx+b -> b = y-mx
			x = (C2intercept-C1intercept)/(C1slope-C2slope)
			y = C1slope*x+C1intercept
			z1angle = -1*(fov[1]/2.)*(combodata[0][i][2]-res[1]/2.)/(res[1]/2.)
			d1 = math.sqrt((x-C1loc[0])**2+(y-C1loc[1])**2)
			z2angle = -1*(fov[1]/2.)*(combodata[1][i][2]-res[1]/2.)/(res[1]/2.)
			d2 = math.sqrt((x-C2loc[0])**2+(y-C2loc[1])**2)
			z1 = math.tan(math.radians(z1angle))*d1
			z2 = math.tan(math.radians(z2angle))*d2
			z = (z1+z2)/2.
			outpoints[k][i] = [i,x,y,z]
		else:
			outpoints[k][i] = [i,0,0,0]
#at this point, outpoints consists of three sets of 3D data points, each computed from a different combination
#of two camera positions (positions 1&2, 2&3, and 3&1)
			
#remove index from the datasets and perform rotations around the Z-axis to align the data points
data0 = np.array(outpoints[0])
data0 = np.delete(data0,0,1)
data1 = np.array(outpoints[1])
data1 = np.delete(data1,0,1)
r = R.from_euler('z',120,degrees=True)
data1 = r.apply(data1)
data2 = np.array(outpoints[2])
data2 = np.delete(data2,0,1)
r = R.from_euler('z',240,degrees=True)
data2 = r.apply(data2)

#turn zeros into NaN so that we don't use zero points (no pixel found) in the averaging below
data0[data0==0] = np.nan
data1[data1==0] = np.nan
data2[data2==0] = np.nan

#simple average of the X, Y, and Z coordinates found from each of the three different camera combinations
#in many cases only two of the three camera locations will have found a pixel.
out = []
for i in range(len(data0)):
	xavg = np.nanmean([data0[i][0],data1[i][0],data2[i][0]])
	yavg = np.nanmean([data0[i][1],data1[i][1],data2[i][1]])
	zavg = np.nanmean([data0[i][2],data1[i][2],data2[i][2]])
	out.append([xavg,yavg,zavg])

#single point linear interpolation of the output to fill in missing points
'''
for i, point in enumerate(out):
	#if point[0] == 0 and i != 0 and i != len(out):
	if point[0] == 0:
		print("FOUND AN EMTPY SPOT")
		print(i)
		try:
			if out[i-1][1] != 0 and out[i+1][1] != 0:
				point[1] = (out[i-1][1] + out[i+1][1])/2.
				point[2] = (out[i-1][2] + out[i+1][2])/2.
				point[3] = (out[i-1][3] + out[i+1][3])/2.
				print(point)
		except:
			print("FAIL")
'''

	
#Create output file in xlights format
#xlights format:
#commas separate columns (width) (X), semicolons separate rows (height) (Y), "|" separate depth (Z)
#pixel numbers (index of pixel) go between

#determine the max size of the matrix to use for the model.  
dataout = np.array(out)/xLights_output_scale_factor   #divide numbers down to a reasonable resolution so the file is not too large
dataout = np.nan_to_num(dataout,copy=False)
dataout = (dataout.round()).astype('i')
xmin = np.nanmin(dataout[:,0])
xmax = np.nanmax(dataout[:,0])
ymin = np.nanmin(dataout[:,1])
ymax = np.nanmax(dataout[:,1])
zmin = np.nanmin(dataout[:,2])
zmax = np.nanmax(dataout[:,2])
#start with a matrix filled with zeros.  
xlout = np.zeros([xmax-xmin,zmax-zmin,ymax-ymin],'i')
#for each pixel, populate the location in the matrix with the index number of the pixel
#locations in the matrix without a pixel will remain zeros



#global axis   xLights axis
#    X             X
#    Y             Z
#    Z             Y
for i, point in enumerate(dataout):
	xlout[point[0]-xmin-1,-1*(point[2]-zmin-1),point[1]-ymin-1] = i+1

#create an output string in xLights format
outstring = ""
for i, z in enumerate(xlout):
	for j, y in enumerate(z):
		for k,x in enumerate(y):
			if x!= 0:
				outstring = outstring + str(x)
			if k != len(y)-1:
				outstring = outstring + ","
		if j != len(z)-1:
			outstring = outstring + ";"
	if i != len(xlout)-1:
		outstring = outstring + "|"
outxml = '<?xml version="1.0" encoding="UTF-8"?><custommodel name="Test" parm1="' + str(xmax-xmin) + '" parm2="' + str(zmax-zmin) + '" Depth="' + str(ymax-ymin) + '" StringType="RGB Nodes" Transparency="0" PixelSize="2" ModelBrightness="" Antialias="1" StrandNames="" NodeNames="" CustomModel="' + outstring + '" SourceVersion="2020.37"  ></custommodel>'
f = open('test.xmodel','w')
f.write(outxml)
f.close()

#plot our points
fig = plt.figure()
ax = fig.add_subplot(111, projection='3d')
ax.scatter(dataout[:,0], dataout[:,1], dataout[:,2])
ax.set_xlabel('X')
ax.set_ylabel('Y')
ax.set_zlabel('Z')
plt.show()
