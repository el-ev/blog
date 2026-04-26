#import "../../driver/template.typ": *
#import "../../driver/form.typ": *

#let title = "Test Form"
#let subtitle = none

#let content = [
  This page tests interactive form components rendered inside and outside SVG.

  $2^31 - 1 =$ #input_field("answer", placeholder: "Your answer").

  #form_button("verify")[Verify]

  #cond(
    "dirty",
    [
      #cond(
        "correct",
        [Correct!],
        [Wrong answer. Try again.],
      )
    ],
    [Please enter an answer and click Verify.],
  )
]

#if sys.inputs.at("with_driver", default: "false") == "false" {
  show: article.with(title: title, subtitle: subtitle)
  content
}
