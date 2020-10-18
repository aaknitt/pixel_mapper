# pixel_mapper
Python scripts for semi-automatic mapping of RGB pixels in 3D space using computer vision.

Output is an xLights file format 3D model of the pixels.

### Prerequisites
Uses  [Lumos library](https://github.com/ptone/Lumos) to control pixels via sACN.

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

## Data Combining & 3D xLights Model Generation
