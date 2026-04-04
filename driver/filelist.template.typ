#let justify_align(left_body, right_body) = {
  block(
    width: 100%,
    [
      #box(width: 1fr)[
        #align(left)[#left_body]
      ]
      #box(width: 1fr)[
        #align(right)[#right_body]
      ]
    ],
  )
}

#set page(
  paper: "iso-b5",
  margin: (x: 1cm, y: 1cm),
  footer: [
    #set text(fill: gray, size: 10pt)
    #justify_align(
      smallcaps(datetime.today().display("Compiled at [year]-[month]-[day]")),
      context counter(page).display(),
    )
  ],
)
#set text(font: "Libertinus Serif", size: 14pt)

= Files

{{FILES}}