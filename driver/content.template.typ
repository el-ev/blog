#import "driver/template.typ": driver_page, a11y_action
#let title = "Blog"
#let subtitle = "It is unlikely that there will be many posts here."
#let export_format = sys.inputs.at("export_format", default: "svg")

#let top_bar = if export_format == "svg" {
  block(
    width: 100%,
    [
      #set text(size: 10pt, fill: luma(100))
      #align(right)[
        #a11y_action("theme", [Theme], label: "Theme")
      ]
    ],
  )
} else {
  none
}

#show: driver_page.with(title: title, subtitle: subtitle, top_bar: top_bar)

= Content
#v(-0.2cm)

{{POSTS}}
