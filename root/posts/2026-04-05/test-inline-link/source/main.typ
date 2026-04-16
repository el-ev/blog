#let title = "Inline Link Test"

#let content = [
This is a test post to ensure links are correctly parsed and rendered in screen readers.
You may ignore this post if you are visually inspecting the rendered SVG image.

Here is a link to #link("https://blog.owo.li", "Homepage").

Here is another link to #link("../../../index.html", "Homepage"), but this one is relative.
]

#if sys.inputs.at("with_driver", default: "false") == "false" {
  import "../../driver/template.typ": article;
  show: article.with(title: title)
  content
}
