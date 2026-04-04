#import "driver/template.typ": base_layout
#let title = "Blog"
#let subtitle = "It is unlikely that there will be many posts here."

#show: base_layout.with(title: title)

#align(center)[
  #text(weight: "bold", size: 24pt)[#title]
  #v(-0.4cm)
  #text(size: 12pt, fill: luma(100))[#subtitle]
]

= Content
#v(-0.2cm)

{{POSTS}}
