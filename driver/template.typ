#import "@preview/digestify:0.1.0": bytes-to-hex, sha1

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

#let base_layout(title: none, body) = {
  if title != none {
    set document(title: title)
  }
  set page(
    paper: "iso-b5",
    margin: (x: 1cm, y: 1cm),
    footer: [
      #set text(fill: gray, size: 10pt)
      #justify_align(
        smallcaps(datetime.today().display("Compiled on [year]-[month]-[day]")),
        context counter(page).display(),
      )
    ],
  )

  set text(font: "Libertinus Serif", size: 12pt)

  show link: it => underline(offset: 2pt, stroke: 0.5pt)[#it]

  body
}

#let with_raw_copy(body) = {
  let raw_copy_enabled = (
    sys.inputs.at("with_driver", default: "false") == "true" and sys.inputs.at("export_format", default: "svg") == "svg"
  )

  let raw_copy_id(text) = "raw-copy-" + bytes-to-hex(sha1(bytes(text))).slice(0, 10)

  let raw_copy_link(content, text) = [
    #show underline: it => it.body
    #link("javascript:parent.copyCode(\"" + raw_copy_id(text) + "\")")[#content]
  ]

  show raw: it => {
    if it.block {
      let content = block(
        fill: luma(245),
        width: 100%,
        inset: 1em,
        radius: 0.3em,
        [
          #set text(size: 0.9em, fill: luma(20))
          #it
        ],
      )
      if raw_copy_enabled {
        raw_copy_link(content, it.text)
      } else {
        content
      }
    } else {
      let content = box(fill: luma(245), inset: (x: 0.2em), outset: (y: 0.2em), radius: 0.2em)[
        #set text(fill: luma(20))
        #it
      ]
      if raw_copy_enabled {
        raw_copy_link(content, it.text)
      } else {
        content
      }
    }
  }

  body
}

#let page_header(title, subtitle: none, date: none) = align(center)[
  #block(text(weight: "bold", size: 24pt)[#title])
  #if subtitle != none {
    v(1em, weak: true)
    text(size: 11pt, fill: luma(100))[#subtitle]
  }
  #if date != none {
    v(1em, weak: true)
    text(size: 11pt, fill: luma(100))[#date]
  }
]

#let driver_page(
  title: "Page",
  subtitle: none,
  date: none,
  top_bar: none,
  justify: false,
  body,
) = {
  show: base_layout.with(title: title)

  if justify {
    set par(justify: true, first-line-indent: 0pt, leading: 0.75em)
    set block(spacing: 1.5em)
  }

  if top_bar != none {
    block(width: 100%)[#top_bar]
  }

  with_raw_copy[
    #page_header(title, subtitle: subtitle, date: date)
    #v(2.5em, weak: true)
    #body
  ]
}

#let article(
  title: "Article",
  date: datetime.today().display(),
  top_bar: none,
  body,
) = {
  driver_page(
    title: title,
    date: date,
    top_bar: top_bar,
    justify: true,
    body,
  )
}
