#assert(sys.inputs.at("with_driver", default: "false") == "true")
#import "driver/template.typ": *

#let export_format = sys.inputs.at("export_format", default: "svg")
#let publish_date = sys.inputs.at("publish_date", default: none)
#let article_date = if publish_date != none {
  publish_date
} else {
  datetime.today().display()
}

#let top_bar = if export_format == "svg" {
  block(
    width: 100%,
    [
      #set text(size: 10pt, fill: luma(100))
      #align(right)[
        #nav_link("../../../index.html", [Contents]) | #nav_link("meta.html", [Meta]) | #nav_link("post.pdf", [PDF]) | #a11y_action("theme", [Theme], label: "Theme")
      ]
    ],
  )
} else {
  none
}

#let subtitle = none

// IMPORT_MAIN

#show: article.with(title: title, subtitle: subtitle, top_bar: top_bar, date: article_date)

#content

#let edited_date = sys.inputs.at("edited_date", default: none)
#if edited_date != none {
  v(1em)
  set text(size: 10pt, fill: luma(100))
  align(right)[Edited on #edited_date]
}

#let last_revision_date = sys.inputs.at("last_revision_date", default: none)
#let last_revision_url = sys.inputs.at("last_revision_url", default: none)
#if last_revision_date != none and last_revision_url != none and export_format == "svg" {
  v(1em)
  set text(size: 10pt, fill: luma(100))
  align(right)[
    Last revision on #link(last_revision_url)[#last_revision_date]
  ]
}
