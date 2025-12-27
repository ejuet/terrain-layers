import bpy

def create_terrain_layers(config):
    pass


def run():
    config = {
        "geometry_modifier_name": "Terrain_Layer_Masks",
        "layers" : [
            {
                "name" : "Underwater",
            },
            {
                "name" : "Beach",
                "mask": {
                    "type": "height",
                    "min_height": 1.5,
                    "max_height": 7.5,
                    "ramp_low": 0.35,
                    "ramp_high": 0.55,
                },
            },
            {
                "name" : "Grass",
                "mask": {
                    "type": "height",
                    "min_height": 3.5,
                    "max_height": 8.0,
                    "ramp_low": 0.45,
                    "ramp_high": 0.65,
                },
            },
            {
                "name" : "Snow",
                "mask": {
                    "type": "height",
                    "min_height": 9.0,
                    "max_height": 15,
                    "ramp_low": 0.45,
                    "ramp_high": 0.65,
                },
            }
        ]
    }

    create_terrain_layers(config)
