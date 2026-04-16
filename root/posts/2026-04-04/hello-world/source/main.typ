#import "../../driver/template.typ": *;

#let title = "Hello, World!"

#let content = [
  This is probably not the first post of this blog.

  But let's say it is, for the sake of tradition.
]

#if sys.inputs.at("with_driver", default: "false") == "false" {
  show: article.with(title: title)
  content
}
