#assert(sys.inputs.at("with_driver", default: "false") == "true")
#import "driver/template.typ": *

#let export_format = sys.inputs.at("export_format", default: "svg")

#let top_bar = if export_format == "svg" {
  block(
    width: 100%,
    [
      #set text(size: 10pt, fill: luma(100))
      #align(right)[
        #link("../../../index.html")[Contents] | #link("post.pdf")[PDF] | #link("source/index.html")[Source]
      ]
    ],
  )
} else {
  none
}

// IMPORT_MAIN

#show: article.with(title: title, top_bar: top_bar)

#content

#let last_revision_date = sys.inputs.at("last_revision_date", default: none)
#let last_revision_url = sys.inputs.at("last_revision_url", default: none)
#if last_revision_date != none and last_revision_url != none and export_format == "svg" {
  v(1em)
  set text(size: 10pt, fill: luma(100))
  align(right)[
    Last revision at #link(last_revision_url)[#last_revision_date]
  ]
}
