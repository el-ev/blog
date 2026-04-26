#import "template.typ": action, _driver_has_driver, _driver_is_svg_export

#let input_field(id, placeholder: "Type here", width: auto) = {
  show underline: it => it.body
  action(
    "input:" + id,
    box(
      width: width,
      baseline: 0.4em,
      stroke: 0.5pt + luma(120),
      radius: 0.2em,
      inset: (x: 0.5em, y: 0.4em),
    )[
      #set text(fill: luma(160))
      #placeholder
    ],
    label: "Input: " + id,
    role: "textbox",
  )
}

#let form_button(id, body) = {
  show underline: it => it.body
  action(
    "form-action:" + id,
    box(
      baseline: 0.3em,
      stroke: 0.5pt + luma(120),
      radius: 0.2em,
      inset: (x: 0.5em, y: 0.3em),
    )[#body],
    role: "button",
  )
}

#let cond(id, if_false, if_true) = {
  if _driver_has_driver() and _driver_is_svg_export() {
    show underline: it => it.body
    context {
      let s0 = measure(if_false)
      let s1 = measure(if_true)
      let w = calc.max(s0.width, s1.width)
      let h = calc.max(s0.height, s1.height)
      box(width: w, height: h)[
        #link("#cond=" + id + ":0")[#if_false]
        #place(top + left)[#link("#cond=" + id + ":1")[#if_true]]
      ]
    }
  } else {
    if_false
  }
}
