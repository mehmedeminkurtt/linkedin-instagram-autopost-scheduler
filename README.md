# Social Media AutoPost Scheduler

A lightweight desktop app for scheduling and publishing social media posts with basic media preparation.

## What it does
- Reads a posting plan from an Excel file (autopost.xlsx)
- Builds posts from a caption + media selection
- Publishes to Instagram (via instagrapi)
- Publishes to LinkedIn using the official LinkedIn API (UGC Posts)

## Configuration
- Copy `config.example.json` to `config.json`
- Put your own credentials and tokens into `config.json`
- Keep `config.json` out of version control

## Templates and overlay (image layout)

The tool can generate image posts using company-branded templates and an optional transparent overlay.

### Files
- `template01.jpg`
- `template02.jpg`
- `transparent.png` (optional, for example a logo or watermark)

### How it works
- A template image is used as the base background.
- The post image is placed onto the template using predefined coordinates and dimensions.
- If provided, the transparent overlay is added on top.

### Adjusting positions and sizes
The placement and size of both the inserted photo and the overlay are defined in the script (x/y position and width/height).
To match a specific brand layout, update those values in the image generation part of the code.

## Notes
- This is not a full production-ready system.
- Credentials, tokens and real integrations are intentionally omitted.
- To post on LinkedIn, you need your own access token and the right permissions enabled for your app.
