# pixel_mapper
Python scripts for semi-automatic mapping of RGB pixels in 3D space using computer vision.

Output is an xLights file format 3D model of the pixels.

### Prerequisites
* [opencv-python](https://pypi.org/project/opencv-python/)
* [Lumos library](https://github.com/ptone/Lumos) to control pixels via E1.31 sACN
* [numpy](https://numpy.org/)
* [imutils](https://pypi.org/project/imutils/)
* [scikit-image](https://scikit-image.org/)
* [playsound](https://pypi.org/project/playsound/)
* [matplotlib](https://matplotlib.org/)

## Workflow Overview
1. Locate camera positions - equilateral triangle around pixel array
2. For each camera location:
   * Level & align camera
   * Capture data using computer vision with manual assist
3. After data from all three cameras is captured:
   * Combine three 2D data files into one xLights 3D model file

## Locate Camera Positions
The three camera locations must be exactly 120 degrees apart around the object to be mapped (in my case, a tree), forming the three vertices of an equilateral triangle.  The camera should be as close to the object/tree as possible while still fully capturing the entire objet witin the field of view.  

Once the required distance from the object has been determined (based on its size and the camera FOV) by moving the camera around and viewing the image, the length of the edges of the equilateral triangle can be determined.  Once these lengths are known, a simple alignment method is to cut three strings to the same length of the triangle edge and pull them tight into the shape of the triangle.  Mark the locations of the three vertices on the ground.  These are the three camera locations that will be used in the following steps.  

<img alt="String Positioning" src="https://raw.githubusercontent.com/aaknitt/pixel_mapper/main/images/StringPosition.jpg" width="40%">

## Camera Alignment
For correct results when translating the three sets of 2D pixel coordinates into one set of 3D coordinates, the camera must be aligned to point directly at the center of the equilateral triangle from each of its three capture locations.  Additionally, the height of the camera at each location must be the same relative to a fixed reference point (not relative to ground, unless the ground is perfectly flat).

Using a camera tripod is highly recommended, as tripods have adjustments to move the camera in all of the required axis and usually have bubble levels built in to aid in leveling.  

Once the camera has been placed directly over its required position on the tripod, the first step is to get the camera leveled.  Once it has been leveled, the camera_align.py script can be run to aid in rotational and vertical alignment.  You'll need to edit the first two lines of code in camera_align.py to specify the resolution of your camera and its VideoCapture source address (an IP address for a WiFi camera or simply an index for a USB camera).  

### Rotational/Horizontal Alignment
First, place some easily visible objects (5 gallon bucket, for example) at the other two camera locations on the equilateral triangle.  The camera on the tripod needs to be aimed so that its center point is directly between the objects.  

camera_align.py will overlay two yellow lines over the camera image.  The location of these lines can be moved in and out by using the right and left arrow keys on the keyboard.  When properly aligned, these yellow lines should pass directly over the two objects (buckets or whatever) that you've placed at the two other camera locations.  

Note that you'll likely need to re-level the camera as you make rotational adjustments.  It doesn't take much movement to bump things out of level.  

### Vertical Alignment
Once the camera is properly aligned horizontally, the last step is to set its vertical location relative to a fixed object.  In my case I manually turned on a single pixel on the tree that I was mapping using the Display Testing function in Falcon Player - FPP.  This pixels was used as my vertical reference point for all three camera locations.  I then raised or lowered the camera on the tripod using the hand crank extension until the blue horizontal overlay line from camer_align.py was directly over the reference pixel.  

## Data Capture
pixel_automap.py is used to capture the data.  This script will be run three times, once with the camera at each of the three locations identified above. 

Depending on your controller configuration, you may need to put it into Bridge Mode to allow it to receive sACN packets from pixel_automap.py.

There are a number of configuration elements at the beginning of the script that will need to be modified to fit your setup.  First, the E1.31 sACN Universes need to be configured.  This will be entirely dependant on the number of pixels you're mapping and how you have the Universes set up in your pixel controller.  You'll also need to specify the camera source to use.  You can also optionally specify an output RGB value to use (default is [100,100,100]) when the pixels are turned on and the name of the output CSV file that is created.  

Once pixel_automap.py is configured and run, it will first turn on all of the pixels that have been configured for E1.31 sACN control and show the camera image.  The user can then click points around the pixels to create a polygon that encompasses all of the pixels.  This polygon will be used as a mask when detecting individual pixels.  Bright lights outside of this polygon will be ignored during the detection process.  Left click to create new points on the polygon and right click to end the polygon.  

After the polygon has been drawn, pixel_automap.py will turn on each individual pixel one at a time and try to detect its location.  If the script is able to detect the location, it will draw a red circle around the pixel, record the coordinats in the output CSV file, and automatically move to the next pixel.  If it us unable to detect the location of the pixel, it will play a sound on the computer to get your attention.  At this point you have two choices to proceed:
1. If you are able to see the location of the pixel, you may click on it.  The coordinates of your click will be used as the pixel location.  
2. If you are anuable to see the location of the pixel (it's on the back side of the tree, for example), simply click anywhere outside the masking polygon.  The coordinates of the pixel will be stored as [0,0] in the output CSV file.

## Data Combining & 3D xLights Model Generation
Once a CSV file has been created for each of the three camera positions, those three CSV files are used by calc_points.py to convert the 2D coordinates captured from each location into a single set of 3D coordinates.  

Strictly speaking, only two camera locations are needed to generate 3D coordinates.  However, because many pixels will be blocked from a single camera location (the tree is not transparent), three positions are used.  

Because there are three camera locations, there are three different combinations of two camera positions that can each be used to generate a set of 3D coordinates (positions 1&2,2&3,3&1).  calc_points.py will calculate a set of 3D coordinates from each 2-camera combination, and then average the three sets of 3D coordinates together to generate the final result.

Once the final set of 3D coordinates has been generated, calc_points.py will then export the final results to an xLights format model file and plot the results for viewing.  
