#import "driver/template.typ": driver_page, action, nav_link, right_top_bar
#let title = "Blog"
#let subtitle = "It is unlikely that there will be many posts here."

#let top_bar = right_top_bar([
  #nav_link("rss.xml", [RSS]) | #action("theme", [Theme], label: "Theme")
])

#show: driver_page.with(title: title, subtitle: subtitle, top_bar: top_bar)

= Content
#v(-0.2cm)

{{POSTS}}
