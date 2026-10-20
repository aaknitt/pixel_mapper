from pathlib import Path
import numpy as np
from scipy.interpolate import interp1d

csv_filename = Path(r"G:\My Drive\House Stuff\Christmas Snowflake LEDs\data\2025\2025_Bush3\Bush3.csv")
xlights_filename = csv_filename.with_suffix(".xmodel")
np.set_printoptions(threshold=np.inf)
MIN_GAP = 3
xLights_output_scale_factor = .5

#points = []
#xlist = []
#ylist = []
out = []
minx = 1e6
miny = 1e6
f = open(csv_filename)
for line in f:
	vals = line.split(',')
	i = int(vals[0])
	x = float(vals[1])
	if x != 0 and x < minx:
		minx = x
	y = float(vals[2])
	if y != 0 and y < miny:
		miny = y
	#xlist.append(x)
	#ylist.append(y)
	#points.append([i,x,y])
	out.append([x,y])
#xlist.sort()
#ylist.sort()
'''
diffx = []
diffy = []
for i in range(len(xlist)-1):
	dx = abs(xlist[i]-xlist[i+1])
	if (dx > 0):
		diffx.append(dx)
	dy = abs(ylist[i]-ylist[i+1])
	if (dy > 0):
		diffy.append(dy)
diffx = list(set(diffx))  #remove duplicates
diffy = list(set(diffy))  #remove duplicates
diffx.sort()
diffy.sort()
print("Min diff in X: ",diffx[0])
print("Min diff in Y: ",diffy[0])
scale = round(max(MIN_GAP / diffx[0], MIN_GAP / diffy[0]))
print("Scale Factor: ",scale)

scale = 1
'''
arr = np.array(out)
x = arr[0:,0]
#x = (x - minx)
x = x*(x>0)
y = arr[0:,1]
#y = (y - miny)
y = y*(y>0)

#turn zeros into NaN so that we can interpolate those points below
x[x==0] = np.nan
y[y==0] = np.nan

def fill_nan(A):
	'''
	interpolate to fill nan values
	https://stackoverflow.com/questions/6518811/interpolate-nan-values-in-a-numpy-array
	'''
	inds = np.arange(A.shape[0])
	good = np.where(np.isfinite(A))
	f = interp1d(inds[good], A[good],fill_value="extrapolate",bounds_error=False,kind='cubic')
	B = np.where(np.isfinite(A),A,f(inds))
	return B

x = fill_nan(x)
print("X",x)
y = fill_nan(y)
print("Y",y)
out = np.stack((y,x),axis=1)

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
#start with a matrix filled with zeros.  
print("xdelta",xmax-xmin)
print("ydelta",ymax-ymin)
print("xmin",xmin)
print("ymin",ymin)
print(len(dataout)," pixels in model")
print('dataout',dataout)

xlout = np.zeros([xmax-xmin,ymax-ymin],'i')

collision_counter = 0
for i, point in enumerate(dataout):
	if xlout[max(point[0]-xmin-1,0),max(point[1]-ymin-1,0)] != 0:
		print("two pixels at ",max(point[0]-xmin-1,0)," "," ",max(point[1]-ymin-1,0))
		collision_counter = collision_counter + 1
	xlout[max(point[0]-xmin-1,0),max(point[1]-ymin-1,0)] = i+1
	if i+1 == 128:
		print('point at i=128',point[0]-xmin-1,point[1]-ymin-1)
	if i + 1 == 1:
		print('point at i=1',point[0]-xmin-1,point[1]-ymin-1)
print(collision_counter," collisions")
print(xlout[256])

#create an output string in xLights format
print("creating xlights file")
outstring = ""
for j, y in enumerate(xlout):  #for each row (y)
	for k,x in enumerate(y):  #for each column/entry in the row (x)
		if x!= 0:
			outstring = outstring + str(x)
		if k != len(y)-1:
			outstring = outstring + ","   
	if j != len(xlout)-1:
		outstring = outstring + ";"

outxml = '<?xml version="1.0" encoding="UTF-8"?><custommodel name="Test" parm1="' + str(xmax-xmin) + '" parm2="' + str(ymax-ymin) + '" StringType="RGB Nodes" Transparency="0" PixelSize="2" ModelBrightness="" Antialias="1" StrandNames="" NodeNames="" CustomModel="' + outstring + '" SourceVersion="2020.37"  ></custommodel>'
print("writing xlights file")
f = open(xlights_filename,'w')
f.write(outxml)
f.close()