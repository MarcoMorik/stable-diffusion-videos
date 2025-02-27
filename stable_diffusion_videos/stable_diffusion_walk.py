import json
import subprocess
from pathlib import Path

import numpy as np
import torch
from diffusers.schedulers import (DDIMScheduler, LMSDiscreteScheduler,
                                  PNDMScheduler)
from diffusers import ModelMixin

from stable_diffusion_videos.stable_diffusion_pipeline import StableDiffusionPipeline


model_id = "runwayml/stable-diffusion-v1-5"

#model_id = "CompVis/stable-diffusion-v1-4"
pipeline = StableDiffusionPipeline.from_pretrained(
    model_id,
    use_auth_token="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",
    torch_dtype=torch.float16,
    revision="fp16",
).to("cuda")

default_scheduler = PNDMScheduler(
    beta_start=0.00085, beta_end=0.012, beta_schedule="scaled_linear"
)
ddim_scheduler = DDIMScheduler(
    beta_start=0.00085,
    beta_end=0.012,
    beta_schedule="scaled_linear",
    clip_sample=False,
    set_alpha_to_one=False,
)
klms_scheduler = LMSDiscreteScheduler(
    beta_start=0.00085, beta_end=0.012, beta_schedule="scaled_linear"
)
SCHEDULERS = dict(default=default_scheduler, ddim=ddim_scheduler, klms=klms_scheduler)


def slerp(t, v0, v1, DOT_THRESHOLD=0.9995):
    """helper function to spherically interpolate two arrays v1 v2"""

    if not isinstance(v0, np.ndarray):
        inputs_are_torch = True
        input_device = v0.device
        v0 = v0.cpu().numpy()
        v1 = v1.cpu().numpy()

    dot = np.sum(v0 * v1 / (np.linalg.norm(v0) * np.linalg.norm(v1)))
    if np.abs(dot) > DOT_THRESHOLD:
        v2 = (1 - t) * v0 + t * v1
    else:
        theta_0 = np.arccos(dot)
        sin_theta_0 = np.sin(theta_0)
        theta_t = theta_0 * t
        sin_theta_t = np.sin(theta_t)
        s0 = np.sin(theta_0 - theta_t) / sin_theta_0
        s1 = sin_theta_t / sin_theta_0
        v2 = s0 * v0 + s1 * v1

    if inputs_are_torch:
        v2 = torch.from_numpy(v2).to(input_device)

    return v2


def make_video_ffmpeg(frame_dir, output_file_name='output.mp4', frame_filename="frame%06d.png", fps=30):
    frame_ref_path = str(frame_dir / frame_filename)
    video_path = str(frame_dir / output_file_name)
    subprocess.call(
        f"ffmpeg -r {fps} -i {frame_ref_path} -vcodec libx264 -crf 10 -pix_fmt yuv420p"
        f" {video_path}".split()
    )
    return video_path


def walk(
        prompts=["blueberry spaghetti", "strawberry spaghetti"],
        seeds=[42, 123],
        num_steps=5,
        output_dir="dreams",
        name="berry_good_spaghetti",
        height=512,
        width=512,
        guidance_scale=7.5,
        eta=0.0,
        num_inference_steps=50,
        do_loop=False,
        make_video=False,
        use_lerp_for_text=True,
        scheduler="klms",  # choices: default, ddim, klms
        disable_tqdm=False,
        upsample=False,
        fps=30,
        less_vram=False,
        resume=False,
        batch_size=1,
        frame_filename_ext='.png',
        latent_interpolation_steps=20,
        strength = 1.0,
):
    """Generate video frames/a video given a list of prompts and seeds.

    Args:
        prompts (List[str], optional): List of . Defaults to ["blueberry spaghetti", "strawberry spaghetti"].
        seeds (List[int], optional): List of random seeds corresponding to given prompts.
        num_steps (int, optional): Number of steps to walk. Increase this value to 60-200 for good results. Defaults to 5.
        output_dir (str, optional): Root dir where images will be saved. Defaults to "dreams".
        name (str, optional): Sub directory of output_dir to save this run's files. Defaults to "berry_good_spaghetti".
        height (int, optional): Height of image to generate. Defaults to 512.
        width (int, optional): Width of image to generate. Defaults to 512.
        guidance_scale (float, optional): Higher = more adherance to prompt. Lower = let model take the wheel. Defaults to 7.5.
        eta (float, optional): ETA. Defaults to 0.0.
        num_inference_steps (int, optional): Number of diffusion steps. Defaults to 50.
        do_loop (bool, optional): Whether to loop from last prompt back to first. Defaults to False.
        make_video (bool, optional): Whether to make a video or just save the images. Defaults to False.
        use_lerp_for_text (bool, optional): Use LERP instead of SLERP for text embeddings when walking. Defaults to True.
        scheduler (str, optional): Which scheduler to use. Defaults to "klms". Choices are "default", "ddim", "klms".
        disable_tqdm (bool, optional): Whether to turn off the tqdm progress bars. Defaults to False.
        upsample (bool, optional): If True, uses Real-ESRGAN to upsample images 4x. Requires it to be installed
            which you can do by running: `pip install git+https://github.com/xinntao/Real-ESRGAN.git`. Defaults to False.
        fps (int, optional): The frames per second (fps) that you want the video to use. Does nothing if make_video is False. Defaults to 30.
        less_vram (bool, optional): Allow higher resolution output on smaller GPUs. Yields same result at the expense of 10% speed. Defaults to False.
        resume (bool, optional): When set to True, resume from provided '<output_dir>/<name>' path. Useful if your run was terminated
            part of the way through.
        batch_size (int, optional): Number of examples per batch fed to pipeline. Increase this until you
            run out of VRAM. Defaults to 1.
        frame_filename_ext (str, optional): File extension to use when saving/resuming. Update this to
            ".jpg" to save or resume generating jpg images instead. Defaults to ".png".

    Returns:
        str: Path to video file saved if make_video=True, else None.
    """
    if upsample:
        from .upsampling import PipelineRealESRGAN

        upsampling_pipeline = PipelineRealESRGAN.from_pretrained('nateraw/real-esrgan')

    if less_vram:
        pipeline.enable_attention_slicing()

    output_path = Path(output_dir) / name
    output_path.mkdir(exist_ok=True, parents=True)
    prompt_config_path = output_path / 'prompt_config.json'

    if not resume:
        # Write prompt info to file in output dir so we can keep track of what we did
        prompt_config_path.write_text(
            json.dumps(
                dict(
                    prompts=prompts,
                    seeds=seeds,
                    num_steps=num_steps,
                    name=name,
                    guidance_scale=guidance_scale,
                    eta=eta,
                    num_inference_steps=num_inference_steps,
                    do_loop=do_loop,
                    make_video=make_video,
                    use_lerp_for_text=use_lerp_for_text,
                    scheduler=scheduler,
                    upsample=upsample,
                    fps=fps,
                    height=height,
                    width=width,
                    latent_interpolation_steps=latent_interpolation_steps,
                    strength=strength,
                ),
                indent=2,
                sort_keys=False,
            )
        )
    else:
        # When resuming, we load all available info from existing prompt config, using kwargs passed in where necessary
        if not prompt_config_path.exists():
            raise FileNotFoundError(
                f"You specified resume=True, but no prompt config file was found at {prompt_config_path}")

        data = json.load(open(prompt_config_path))
        prompts = data['prompts']
        seeds = data['seeds']
        num_steps = data['num_steps']
        height = data['height'] if 'height' in data else height
        width = data['width'] if 'width' in data else width
        guidance_scale = data['guidance_scale']
        eta = data['eta']
        num_inference_steps = data['num_inference_steps']
        do_loop = data['do_loop']
        make_video = data['make_video']
        use_lerp_for_text = data['use_lerp_for_text']
        scheduler = data['scheduler']
        disable_tqdm = disable_tqdm
        upsample = data['upsample'] if 'upsample' in data else upsample
        fps = data['fps'] if 'fps' in data else fps

        resume_step = int(sorted(output_path.glob(f"frame*{frame_filename_ext}"))[-1].stem[5:])
        print(f"\nResuming {output_path} from step {resume_step}...")

    if upsample:
        from .upsampling import PipelineRealESRGAN

        upsampling_pipeline = PipelineRealESRGAN.from_pretrained('nateraw/real-esrgan')

    pipeline.set_progress_bar_config(disable=disable_tqdm)
    pipeline.scheduler = SCHEDULERS[scheduler]

    assert len(prompts) == len(seeds)

    first_prompt, *prompts = prompts
    embeds_a = pipeline.embed_text(first_prompt)

    first_seed, *seeds = seeds
    latents_a = torch.randn(
        (1, pipeline.unet.in_channels, height // 8, width // 8),
        device=pipeline.device,
        generator=torch.Generator(device=pipeline.device).manual_seed(first_seed),
    )

    if do_loop:
        prompts.append(first_prompt)
        seeds.append(first_seed)

    frame_index = 0
    old_latent = None

    for prompt, seed in zip(prompts, seeds):
        # Text
        embeds_b = pipeline.embed_text(prompt)

        # Latent Noise
        latents_b = torch.randn(
            (1, pipeline.unet.in_channels, height // 8, width // 8),
            device=pipeline.device,
            generator=torch.Generator(device=pipeline.device).manual_seed(seed),
        )

        latents_batch, embeds_batch = None, None
        for i, t in enumerate(np.linspace(0, 1, num_steps)):

            frame_filepath = output_path / (f"frame%06d{frame_filename_ext}" % frame_index)
            if resume and frame_filepath.is_file():
                frame_index += 1
                continue

            if use_lerp_for_text:
                embeds = torch.lerp(embeds_a, embeds_b, float(t))
            else:
                embeds = slerp(float(t), embeds_a, embeds_b)
            latents = slerp(float(t), latents_a, latents_b)

            embeds_batch = embeds if embeds_batch is None else torch.cat([embeds_batch, embeds])
            latents_batch = latents if latents_batch is None else torch.cat([latents_batch, latents])

            del embeds
            del latents
            torch.cuda.empty_cache()

            batch_is_ready = embeds_batch.shape[0] == batch_size or t == 1.0
            if not batch_is_ready:
                continue

            do_print_progress = (i == 0) or ((frame_index) % 20 == 0)
            if do_print_progress:
                print(f"COUNT: {frame_index}/{len(seeds) * num_steps}")

            with torch.autocast("cuda"):
                outputs = pipeline(
                    latents=latents_batch,
                    text_embeddings=embeds_batch,
                    height=height,
                    width=width,
                    guidance_scale=guidance_scale,
                    eta=eta,
                    num_inference_steps=num_inference_steps,
                    output_type='pil' if not upsample else 'numpy',
                    strength=strength if old_latent is not None else 1.0,
                    prev_img=old_latent,
                )
                vae_latent = outputs["latent"]
                if latent_interpolation_steps:
                    dims = vae_latent.shape
                    if dims[0] >1:
                        #Within Batch interpolation
                        cur = torch.stack([torch.lerp(vae_latent[:-1], vae_latent[1:], float(i) / latent_interpolation_steps) for i in
                                           range(1, latent_interpolation_steps)], 1).reshape((-1,*dims[1:]))
                    else:
                        #We have no interpolation within a Batch
                        cur = torch.tensor([],device=vae_latent.device)

                    if old_latent is not None:
                        #Interpolation from previous batch
                        prev = torch.stack([torch.lerp(old_latent, vae_latent[:1], float(i) / latent_interpolation_steps) for i in
                                            range(1, latent_interpolation_steps)], 1).reshape((-1, *dims[1:]))

                        intermediate_latents = torch.cat((prev,cur),dim=0)
                        del prev
                        del cur
                    else:
                        intermediate_latents = cur

                    print("we do intermediate interpolation", intermediate_latents.shape)
                    if intermediate_latents.shape[0] >0:
                        with torch.no_grad():
                            for i in range(0,intermediate_latents.shape[0] ):
                                outputs = pipeline.vae.decode(intermediate_latents[i:i+1]).sample
                                outputs = (outputs / 2 + 0.5).clamp(0, 1)
                                outputs = outputs.cpu().permute(0, 2, 3, 1).numpy()
                                outputs = pipeline.numpy_to_pil(outputs)

                                if upsample:
                                    images = []
                                    for img in outputs:
                                        images.append(upsampling_pipeline(img))
                                else:
                                    images = outputs
                                for img in images:
                                    frame_filepath = output_path / (f"frame%06d{frame_filename_ext}" % frame_index)
                                    img.save(frame_filepath)
                                    frame_index += 1
                        del images

                    old_latent = vae_latent[-1:]

                    del intermediate_latents
                else:

                    outputs = outputs["sample"]
                    if upsample:
                        images = []
                        for output in outputs:
                            images.append(upsampling_pipeline(output))
                    else:
                        images = outputs
                    for image in images:
                        frame_filepath = output_path / (f"frame%06d{frame_filename_ext}" % frame_index)
                        image.save(frame_filepath)
                        frame_index += 1


                del embeds_batch
                del latents_batch
                torch.cuda.empty_cache()
                latents_batch, embeds_batch, intermediate_latents = None, None, None


        embeds_a = embeds_b
        latents_a = latents_b

    if make_video:
        return make_video_ffmpeg(output_path, f"{name}.mp4", fps=fps, frame_filename=f"frame%06d{frame_filename_ext}")


if __name__ == "__main__":
    text_owl = ["A realistic painting of a owl flying through a colorful landscape.",
            "A beautiful painting of an owl flying towards a forest.",
            "A painting of an owl finding a pill in the forest.",
            "A artistic cartoon of a owl swallow a pill in the forest.",
            "A colorful trippy painting of a owl in a forest.",
            "A trippy illustration of a owl. The Bottom is Colorful, while the top is black and white.",
            "A painting of a spooky horrible forest. In the middle is a bleeding owl. The eyes are scary.",
            "A horrifying cartoon of a dying owl, stabbed by a knife.",
            "A sad funeral of birds grieve for the dead owl.",  # 97 ?
            "A horrfying painting of a oak tree growing over the grave.",  # 97
            "The owl is flying towards hell, burning to ashes, abstract horrifying art",
            "front!!! shot of a Owl!!! character, mesmerizing fractal hypercubes, platinum cracked, dark holography!!!, future, metallic galactic, crystalline edges, polygonal, elegant, highly detailed, centered, (((artstation, concept art, jagged, sharp focus, artgerm, Tomasz Alen Kopera, Peter Mohrbacher, donato giancola, Joseph Christian Leyendecker, WLOP, Boris Vallejo))), ((raytracing)), octane render, nvidia raytracing demo, octane render, nvidia raytracing demo, octane render, nvidia raytracing demo, 8K, cinematic, masterpiece"
            "A trippy sign of The End",
    ]
    seed_owl = [15, 13, 13, 7532, 2001, 1993, 21534, 2234, 97, 97, 97, 2001,436450127]

    text = ["A scarry cartoon of a robot walking through a dark forest"] + \
           ["A black and white cartoon of a robot finding a glowing redstone in the forest."] + \
           ["A black and white drawing of a robot picking up a magic redstone in the forest."] + \
           [
               "An painting of robot picking up a magic redstone in the forest. The forest is black and white and just the robot and stone is colorful."] + \
           ["A colorful trippy painting of a robot with a redstone in the forest."] + \
           ["A colorful trippy painting of a robot with a redstone in the forest."] + \
           ["A colorful trippy illustration of a robot with a redstone in a mystic forest."] * 7 + \
           ["A trippy colorful painting of a robot flying on a rock through space."] * 2 + \
           ["A trippy dark painting of a robot landing in a spooky forest"] * 3 + \
           ["A horrifying creeper chains and strangulats a helpless robot in the forest. As scary drawing."] + \
           ["A group of crows attacking the robot. As fearful illustration."] + \
           ["A robot is impaled by a spooky Oak tree, screaming full of paint. Abstract art."] * 2 + \
           ["A peaceful green forest with pieces of a robot lying around on the ground. As naturalistic painting."] + \
           ["The spooky ghost of a robot haunting the mystic forest by night."]
    seed = [21, 29, 256, 1234567890, 1993, 2001, 2101, 2, 15777546702, 13331211]
    seed = [21, 21, 2, 29,
            29, 256,
            21, 29, 1234567890, 2001, 2101, 15777546702, 2,
            29, 2101,
            2001, 21, 15777546702,
            21,
            256,
            2, 21,
            256,
            2001]

    text_group = [
        "A group of Friends standing on an old, rusty, spooky attic, drinking a beer, Studio ghibli,  dark drawing, concept art",
        "A human-sized bottle of beer, holding a knife in its hand, lurking from behind a corner with an evil grin, greg rutkowski, sung choi, mitchell mohrhauser, maciej kuciara, johnson ting, maxim verehin, peter konig, bloodborne, 8 k photorealistic, cinematic lighting, hd, high details, dramatic, dark atmosphere, trending on artstation",

    ]
    text_group = ["A group of friends standing on an old, rusty, spooky attic, drinking a beer, Studio ghibli, dark drawing, concept art",
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

    text_wald = []
    seed_wald = []
    for strength in [1.0,0.9,0.8,0.75,0.7,0.65]:
        ##seed = [s] * len(text)

        video_path = walk(text, seed, num_steps=60, output_dir="imgs", name=f"NewOldRobotStrength{strength}", make_video=True,height=512,
            width=512, scheduler="ddim",
                      latent_interpolation_steps=5, do_loop=True, batch_size=16,strength=strength)

    #import fire

    #fire.Fire(walk)
