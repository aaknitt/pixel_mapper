# pixel_mapper
Semi-automatic mapping of RGB pixels in 3D space using computer vision.

Output is an xLights file format 3D model of the pixels.

Uses  [Lumos library](https://github.com/ptone/Lumos)to control pixels via sACN.

Workflow Overview
1. Locate camera positions - equilateral triangle around pixel array
2. For each camera location:
   * Level & align camera
   * Capture data using computer vision with manual assist
3. After data from all three cameras is captured:
   * Combine three 2D data files into one xLights 3D model file

Camera Alignment
For correct results when translating the three sets of 2D pixel coordinates into one set of 3D coordinates, the camera must be aligned to point at the exact center of the equilateral triangle from each of its three capture locations.  Additionally, the height of the cameras at each location must be the same relative to a fixed reference point (not relative to ground, unless the ground is perfectly flat).

Using a camera tripod is highly recommended, as tripods have adjustments to move the camera in all of the required axis and usually have bubble levels built in to aid in leveling.  


Once the camera has been placed directly over its requried position on the tripod, the first step is to get the camera leveled.  Once it has been leveled, the camera_align.py script can be run to aid in rotational and vertical alignment.  

Rotational/Horizontal Alignment
First, place some easily visible objects (5 gallon bucket, for example) at the other two camera locations on the equilateral triangle.  The camera on the tripod needs to be aimed so that its center point is directly between the objects.  

camera_align.py will overlay two yellow lines over the camera image.  The location of these lines can be moved in and out by using the right and left arrow keys on the keyboard.  When properly aligned, these yellow lines should pass directly over the two objects (buckets or whatever) that you've placed at the two other camera locations.  

Note that you'll likely need to re-level the camera as you make rotational adjustments.  It doesn't take much movement to bump things out of level.  

Vertical Alignment
Once the camera is properly aligned horizontally, the last step is to set its vertical location relative to a fixed object.  In my case I manually turned on a single pixel on the tree that I was mapping using the Display Testing function in Falcon Player - FPP.  This pixels was used as my vertical reference point for all three camera locations.  I then raised or lowered the camera on the tripod using the hand crank extension until the blue horizontal overlay line from camer_align.py was directly over the reference pixel.  
