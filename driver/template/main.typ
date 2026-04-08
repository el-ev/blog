#import "../../driver/template.typ": *;

#let title = "Your Article Title"

#let content = [
  Write your article here.
]

#if sys.inputs.at("with_driver", default: "false") == "false" {
  show: article.with(title: title)
  content
}
