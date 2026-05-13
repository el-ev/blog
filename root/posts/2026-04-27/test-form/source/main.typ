#import "../../driver/template.typ": *
#import "../../driver/form.typ": *

#let title = "Test Form"
#let subtitle = none

#let content = [
  This page tests interactive form components rendered inside and outside SVG.

  == Input

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

  == Checkboxes

  #checkbox("item_1")[Item 1] \
  #checkbox("item_2")[Item 2]

  #cond("summary", [_No options enabled._], [_Some options are enabled._])

  == Radio buttons

  Pick a _color_:

  #radio("color", "red")[Red]
  #radio("color", "green")[Green]
  #radio("color", "blue")[Blue]

  #cond("color-picked", [_No color selected._], [])
  #cond("color-red", [], [You picked #text(fill: red)[_red_].])
  #cond("color-green", [], [You picked #text(fill: green)[_green_].])
  #cond("color-blue", [], [You picked #text(fill: blue)[_blue_].])
]

#if sys.inputs.at("with_driver", default: "false") == "false" {
  show: article.with(title: title, subtitle: subtitle)
  content
}
