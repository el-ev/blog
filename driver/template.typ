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
    ]
  )
}

#let article(
  title: "Article",
  date: datetime.today().display(),
  top_bar: none,
  body,
) = {
  set document(title: title)
  set page(
    paper: "iso-b5",
    margin: (x: 1cm, y: 1cm),
    footer: [
      #set text(fill: gray, size: 10pt)
      #justify_align(
        smallcaps(datetime.today().display("Compiled at [year]-[month]-[day]")),
        context counter(page).display()
      )
    ],
  )
  
  set text(font: "Libertinus Serif", size: 12pt)
  set par(justify: true, first-line-indent: 0pt)
  show link: underline

  if top_bar != none {
    top_bar
  }

  align(center)[#text(weight: "bold", size: 16pt)[#title]]
  v(-0.4cm)
  align(center)[#date]

  body
}


