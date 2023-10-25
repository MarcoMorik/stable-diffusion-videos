text = [
    "A group of friends standing on an old, rusty, spooky attic, drinking a beer, Studio ghibli, dark drawing, concept art",
    "A human-sized bottle of beer with an evil grin, holding a knife in its hand, lurking from behind a corner, gritty industrial style",
    "A poison dart frog inside of an beer bottle, azur blue, death, digital art, glowing",
    "A blue human sized demon frog smokes a cigar, trending on artstation, trippy art",
    "A Frog disapearing in smoke, Fractals, DMT, trippy, LSD, Art",
    "A heroic wine bottle base jumps frome above with a parachute to free the cigar from the human sized demon frog, detailed colorful rendering, 4k, trending on artstation",
    "The human sized demon frog starts a katana sword fight with the heroic wine bottle, studio ghibli, digital art, drawing, vibrant, dark, demon, death",
    "The human sized wine bottle gets hit by the sword and red wine starts to run out of it,  Studio ghibli, dark drawing, concept art",
    "The human sized wine bottle holds its wound and cries bitterly while the human sized beer bottle laughs viciously, Studio ghibli, dark drawing, concept art, trending on artstation",
    "The human sized wine bottle lets out its last breath, Studio ghibli, trippy fantasy rendering, 4k",
    "Everyone thought the human sized wine bottle just died, but in a surprising moment of bright, blinding light the human sized wine bottle ejects into the sky, propelled by a wooden kite, detailed animation movie, 4k "
    "The human sized wine bottle slowly disappears into the sun while shrinking to normal size, romantic ending, landscape, oil painting",
    "The bottle in the sky breaks into a million sparkling pieces that spread over the night sky, digital art, octane render, dramatic, apocalyptic, cinematic rendering, 8k "
    ]

seeds = [29102022,
         10020202,
         19081993,
         101010101010,
         20010507,
         1234567890,
         12,
         2017
         ]


import shutil
import os
for seed in seeds:
    folder = f"GroupStorySeed{seed}/"
    for i in [8]:#range(0,23,2):
        src = f"{folder}frame%06d.png" % i
        dst_folder = f"imgs/{i//2}{text[i//2][:120]}/"
        os.makedirs(dst_folder, exist_ok=True)
        dst = f"{dst_folder}Seed{seed}.png"
        shutil.copyfile(src, dst)