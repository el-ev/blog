#import "driver/template.typ": base_layout
#let title = "Metadata"

#show: base_layout.with(title: title)

#align(center)[
  #text(weight: "bold", size: 24pt)[#title]
  #v(-0.4cm)
]

{{META_FIELDS}}

= Source Files

{{SOURCE_FILES}}
