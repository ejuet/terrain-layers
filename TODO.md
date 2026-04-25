# To Do's

## Current

- [ ] Restructure config
  - [ ] so road networks are not just a mask but an extra thing
  - [ ] and biomes are also not just part of a layer but can have multiple layers
- [ ] Scatter Objects alongside paths

## Future

- [ ] Make scatter biomes have multiple layers depending on objects, e.g. dirt beneath trees and grass everywhere else. Needs restructuring of the pipeline/ config

## Minor

- [ ] Specify multiple terrain objects/ a collection instead of just one
- [ ] See if there is a more convenient way of importing textures

## Done

- [X] Paths that create layers
- [X] Find out why roads with fallout=0 still have smooth edges => use settings `falloff=0,ramp_low=0, ramp_high=0.15` to get sharper edges
- [X] Modify config so that there is a class RoadNetwork that can contain multiple path objects and/or multiple blender-collections of paths. For each path object or collection, you can redefine the road width etc. The road network has a property path_settings, but they can be overridden by the individual paths or collections
  - This will also later allow us to have specific scatter settings for each path of a network, e.g. the road network defines that there are lampposts every 5m, but for one street, they are every 2m and for one street, there are no lampposts at all. These settings override the road network settings
- [X] Flatten/ Smooth terrain on paths
- [X] Restructure this so it is a proper python module but still works as a blender addon with hot reloading
- [X] Think about how to handle bridges and tunnels
  - Bridges: Created manually, curves should go over the bridge, and then the bridge should be added in the config as well so that we know that we can exclude this area from texturing, scattering and path deformation etc.
  - Tunnels: See if we can write a tunnel modifier that deforms the terrain to create a tunnel between the endpoints of the tunnel/ bezier curve
    - See chat: boolean subtraction. maybe we turn the terrain into a solid chunk, do the tunneling, turn the tunnel into an extra mesh, then turn the terrain back into a heightmap and remove the vertices at the entry of the tunnel
- [X] Add scatter biome settings for rotation, e.g. so that trees are always upright and not along the normal of the terrain