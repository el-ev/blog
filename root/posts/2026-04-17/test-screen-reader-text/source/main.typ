#import "../../driver/template.typ": *;

#let title = "Test Screen Reader Text"

#let content = [
  Posts on this blog are compiled to SVG pages, which provides a consistent visual appearance but leaves assistive technology with nothing to announce. To fix the accessibility issue, the template wraps each semantic element in a `#metadata(..) <driver-doc>` node, and the build script runs `typst query` to pull that tree out and rebuild an HTML version of the post inside a `<div class="sr-only">` block ahead of the image. This post exercises that pipeline: every common Typst element appears below so that a screen reader can verify extraction.

  == Paragraphs and emphasis

  This is a plain paragraph. It contains some *bold text*, some _italicized phrasing_, and the occasional `inline code span`. All three should appear with their semantic wrappers intact.

  == Inline links

  A link to #link("https://blog.owo.li", "the homepage") should be announced as link text, not as a raw URL. A second link to #link("https://typst.app", "Typst") keeps the destination within the anchor.

  == Lists

  Unordered list:

  - First bullet.
  - Second bullet with an `inline code fragment` inside.

  Ordered list:

  + Step one.
  + Step two.
  + Step three.

  == Code block

  ```rust
  fn greet(name: &str) {
      // This looks like a comment
      println!("Hello, {name}!");
  }
  ```

  == Block quote

  #quote(block: true, attribution: [Donald Knuth])[
    Premature optimization is the root of all evil.
  ]

  == Math

  Inline math: $e^(i pi) + 1 = 0$.

  Block math follows:

  $ integral_0^infinity e^(-x^2) dif x = sqrt(pi) / 2 $

  Math equations are currently converted to raw source text, which is not ideal, but at least ensures that the content is not lost. A future improvement would be to render them in MathML or a similar format for better screen reader support.

  == Table

  #table(
    columns: (auto, auto, auto),
    [*Element*], [*Purpose*], [*Tested?*],
    [heading], [section break], [yes],
    [raw], [code snippets], [yes],
    [table], [tabular data], [yes],
  )

  == Figure

  #figure(
    image("gradient.png", width: 60%, alt: "A small gradient image used as a placeholder for testing"),
    caption: [A test figure with alt text and a caption.],
  )

  == Custom elements

  #info(
    [
      Information blocks are converted to `<aside>` elements.
    ],
  )

  == Closing

  If every element above is readable in the `sr-only` block, extraction is working. If anything is missing or garbled, refer to the PDF version as a reference.
]

#if sys.inputs.at("with_driver", default: "false") == "false" {
  import "../../driver/template.typ": article
  show: article.with(title: title)
  content
}
