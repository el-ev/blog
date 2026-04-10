# blog

Typst-based blog pipeline and one deployment example.

## Requirements
- `python3`
- `typst` on `PATH`
- `svgo` on `PATH` (SVG optimization)
- `terser` on `PATH` (JavaScript minification)

```bash
npm install --global svgo terser
```

## Quick start
```bash
# create a draft in workspace/my-post/
python3 driver/main.py init my-post

# compile into build/
python3 driver/main.py compile my-post

# publish to root/posts/YYYY-MM-DD/my-post/
python3 driver/main.py submit my-post

# rebuild root/index.html + root/sitemap.xml
python3 driver/main.py update
```

## Useful commands
```bash
python3 driver/main.py recover my-post --force
python3 driver/main.py amend-all
python3 driver/main.py upload --config config.json
```

This deploys to GCS. You may ignore it and upload `root/` to anywhere you like.

## Layout
- `driver/`: CLI + templates
- `workspace/`: local drafts (gitignored)
- `build/`: transient compile output (gitignored)
- `root/`: published static site

Start from `config.example.json` for deploy settings; keep `config.json` private.

## License

Code in this repository is licensed under the MIT License. Articles under `root/` are All Rights Reserved.
