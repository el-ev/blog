#import "../../driver/template.typ": *;

#let title = "Preload SVG Sprites"
#let subtitle = [You can't preload SVG sprites, but you can.]

#let content = [
  #info[
    *TL;DR:* Insert an invisible image referencing the sprite sheet to load on the top of the page.
  ]
  #info[
    The title is borrowed from #link("https://geoffrich.net/posts/preloading-svgs/", "You can’t preload SVG sprites (but I want to)").
  ]

  So I ran into this problem for this specific blog setup: A lot of posts, a lot of SVG pages, the same set of glyphs used across all pages. Keeping a copy of all the glyphs in each page is a waste of bandwidth and hurts loading speed, so I pulled them out into a shared sprite sheet and referenced them like this:

  ```xml
  <symbol id="a" ><use href="assets/glyphs.svg#g7q"/>
  ```

  That works as intended, but problem comes: glyphs file is loaded only when the *first* page that references it is loaded. On a fresh visit, readers would stare at a blank page for some hundreds of milliseconds or longer, which is not great.

  #numbered_image(
    image(
      "deferred.png",
      width: 50%,
      alt: "A screenshot of developer tools showing that the glyphs file is loaded only after the page is loaded",
    ),
    "deferred loading of the glyphs file",
  )

  When you want to preload an asset, you use `<link rel="preload" ...>`, and that's exactly what I did next:

  ```html
  <link rel="preload" as="image" href="assets/glyphs.svg"/>
  ```

  ...and ended up with the file being downloaded *twice*.

  #numbered_image(
    image(
      "duplicated.png",
      width: 50%,
      alt: "A screenshot of developer tools showing that the glyphs file is loaded twice",
    ),
    "glyphs loaded twice, once by preload and once by the page",
  )

  I'm not an expert in frontend stuff, so I asked the models, spent a hour tampering with `as="image"`, `as="fetch"` and `crossorigin` attributes, but nothing worked. Then I came across the article linked at the top and learned that this is a well-known limitation.

  At that point I figured: If the browser only loads the sprite when it sees a reference to it, why don't I insert a small image to load it before the pages are loaded? So I added this line:

  ```html
  <svg aria-hidden="true" width="0" height="0" style="position:absolute;opacity:0;pointer-events:none"><use href="./assets/glyphs.svg#g1"></use></svg>
  ```

  I should say it does work. Although the glyphs file is still not fully loaded (it is over 80 KiB!) until the pages has been loaded on the first visit, it still cuts the black screen time by three quarters.
  On subsequent visits to any page, it become instant.

  #numbered_image(
    image(
      "preloaded.png",
      width: 50%,
      alt: "A screenshot of developer tools showing that the glyphs file is loaded before the pages ar loaded",
    ),
    "glyphs file is loaded before the pages are loaded",
  )

  #strike[
    You can visit my blog to see the effect in action: #link("https://blog.owo.li", "Blog")
  ]

  And that is the end of the story.
]

#if sys.inputs.at("with_driver", default: "false") == "false" {
  show: article.with(title: title, subtitle: subtitle)
  content
}
