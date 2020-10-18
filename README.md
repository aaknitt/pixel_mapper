# pixel_mapper
Semi-automatic mapping of RGB pixels in 3D space using computer vision.

Output is an xLights file format 3D model of the pixels.

Uses  [Lumos library](https://github.com/ptone/Lumos)to control pixels via sACN.

Workflow Overview
1) Locate camera positions - equilateral triangle around pixel array
For each camera location:
2) Level & high-align camera
3) Capture data using computer vision with manual assist
After data from all three cameras is captured:
4) Combine three 2D data files into one xLights 3D model file

