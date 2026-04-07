#import "driver/template.typ": driver_page
#let title = "Blog"
#let subtitle = "It is unlikely that there will be many posts here."

#show: driver_page.with(title: title, subtitle: subtitle)

= Content
#v(-0.2cm)

{{POSTS}}
