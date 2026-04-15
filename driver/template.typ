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

#let info(body) = block(
  fill: luma(248),
  stroke: (left: 0.18em + luma(120)),
  width: 100%,
  inset: (x: 1em, y: 0.85em),
  radius: 0.15em,
  [
    #set text(fill: luma(20))
    #body
  ],
)

#let numbered_image(image_body, description) = figure(
  image_body,
  caption: [#description],
)

#let numbered_table(description, ..table_args) = figure(
  table(..table_args),
  caption: [#description],
)

#let base_layout(title: none, page_margin: (x: 1cm, y: 1cm), body) = {
  if title != none {
    set document(title: title)
  }
  set page(
    paper: "iso-b5",
    margin: page_margin,
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

#let nav_link(href, body) = link(href)[#body]

#let _driver_has_driver() = sys.inputs.at("with_driver", default: "false") == "true"
#let _driver_is_svg_export() = sys.inputs.at("export_format", default: "svg") == "svg"

#let right_top_bar(body, svg_only: true) = {
  if svg_only and not _driver_is_svg_export() {
    none
  } else {
    block(
      width: 100%,
      [
        #set text(size: 10pt, fill: luma(100))
        #align(right)[#body]
      ],
    )
  }
}

#let action(action, body, label: none, role: "button", tabindex: none) = {
  let label_metadata = if label == none {
    ""
  } else {
    "|label:" + label
  }
  let role_metadata = if role == none {
    ""
  } else {
    "|role:" + role
  }
  let tabindex_metadata = if tabindex == none {
    ""
  } else {
    "|tabindex:" + tabindex
  }
  link("#action=" + action + label_metadata + role_metadata + tabindex_metadata)[#body]
}

#let copy_action(body, text, skip_tab: false) = {
  show underline: it => it.body
  action(
    "copy:" + bytes-to-hex(sha1(bytes(text))).slice(0, 10),
    body,
    label: "Copy",
    tabindex: if skip_tab { "-1" } else { none },
  )
}

#let with_raw_copy(body) = {
  let raw_copy_enabled = _driver_has_driver() and _driver_is_svg_export()

  show raw: it => {
    if it.block {
      let content = block(
        fill: luma(245),
        width: 100%,
        inset: 1em,
        breakable: true,
        radius: 0.3em,
        [
          #set text(size: 0.9em, fill: luma(20))
          #it
        ],
      )
      if raw_copy_enabled {
        copy_action(content, it.text)
      } else {
        content
      }
    } else {
      let content = box(fill: luma(245), inset: (x: 0.2em), outset: (y: 0.2em), radius: 0.2em)[
        #set text(fill: luma(20))
        #it
      ]
      if raw_copy_enabled {
        copy_action(content, it.text, skip_tab: true)
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
  page_margin: (x: 1cm, y: 1cm),
  body,
) = {
  show: base_layout.with(title: title, page_margin: page_margin)

  let back_href = sys.inputs.at("back_href", default: "./index.html")

  let default_top_bar = right_top_bar(
    [
      #nav_link(back_href, [Back]) | #action("theme", [Theme], label: "Theme")
    ],
  )

  let resolved_top_bar = if top_bar != none {
    top_bar
  } else {
    default_top_bar
  }

  if justify {
    set par(justify: true, first-line-indent: 0pt, leading: 0.75em)
    set block(spacing: 1.5em)
  }

  if resolved_top_bar != none {
    block(width: 100%)[#resolved_top_bar]
  }

  with_raw_copy[
    #page_header(title, subtitle: subtitle, date: date)
    #v(2.5em, weak: true)
    #body
  ]
}

#let article(
  title: "Article",
  subtitle: none,
  date: datetime.today().display(),
  top_bar: none,
  body,
) = {
  driver_page(
    title: title,
    subtitle: subtitle,
    date: date,
    top_bar: top_bar,
    justify: true,
    body,
  )
}
