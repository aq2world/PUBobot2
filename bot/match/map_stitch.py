from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO
import os
from core.console import log
from tempfile import NamedTemporaryFile

def map_stitch(maps: list):
    base_url = 'https://raw.githubusercontent.com/vrolse/AQ2-pickup-bot/main/thumbnails/'
    image_urls = [base_url + name + '.jpg' for name in maps]
    # Download the images
    images = []
    for url in image_urls:
        try:
            images.append(Image.open(BytesIO(requests.get(url).content)))
        except Exception:
            if images:
                # Create a new black image with the same size as the previous image
                images.append(Image.new('RGB', images[-1].size))
            else:
                # If it's the first image, create a new black image with a default size
                images.append(Image.new('RGB', (100, 100)))

    # Calculate the width and height of the new image
    max_width = max(image.width for image in images)
    max_height = max(image.height for image in images)
    total_width = max_width * 3
    total_height = max_height * 3

    # Create a new image with the calculated width and height
    new_image = Image.new('RGB', (total_width, total_height))

    # Create a draw object
    draw = ImageDraw.Draw(new_image)

    # Load a system font
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 100)

    # Paste each image into the new image at the correct position and draw the filename
    try:
        for i, (image, url) in enumerate(zip(images, image_urls)):
            x = i % 3 * max_width
            y = i // 3 * max_height
            new_image.paste(image, (x, y))            
            # Draw the filename
            filename = os.path.splitext(url.split('/')[-1])[0]  # remove the extension
            text_width = draw.textlength(filename, font=font)
            text_x = x + (max_width - text_width) / 2
            text_y = y
            draw.text((text_x, text_y), filename, fill='white', font=font)
    except Exception as e:
        log.error("\n Error creating map collage: " + str(e) + "\n")

    # Save the new image
    imgfile = NamedTemporaryFile(suffix=".jpg", delete=False)
    new_image.save(imgfile.name)
    return imgfile.name