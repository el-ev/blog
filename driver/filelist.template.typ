#import "driver/template.typ": base_layout
#let title = "Files"

#show: base_layout.with(title: title)

#align(center)[
  #text(weight: "bold", size: 24pt)[#title]
  #v(-0.4cm)
]

= Content

{{FILES}}