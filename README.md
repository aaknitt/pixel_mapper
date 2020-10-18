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

