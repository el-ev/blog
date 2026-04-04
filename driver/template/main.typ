#let title = "Your Awesome Article"

#let content = [
  Place your article content here.
]

#if sys.inputs.at("with_driver", default: "false") == "false" {
  import "../../driver/template.typ": article;
  show: article.with(title: title)
  content
}
