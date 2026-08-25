// templates/typst-classic/template.typ
// A5 단행본/교재. Variables filled by typesetter.

// Placeholders land only in string literals so the typesetter's
// string-escaping is sufficient even for titles with markup characters.
#let book-title = "{{title}}"
#let book-author = "{{author}}"

#set document(title: book-title, author: book-author)

#set page(
  paper: "a5",
  margin: (x: 18mm, y: 24mm),
  number-align: center,
  numbering: none,
  header: none,
)

#set text(
  font: ("Source Serif 4", "Noto Serif KR", "Malgun Gothic", "Batang", "Times New Roman"),
  size: 11pt,
  lang: "{{lang}}",
)
#set par(
  justify: true,
  leading: 0.95em,
  spacing: 1.5em,
  first-line-indent: (amount: 1.2em, all: false),
)
#set heading(numbering: "1.1")

// State flag: are we currently inside the BODY section?
#let in_body = state("in_body", false)

// Level-1 (chapter) — body chapters get the elaborate start page
#show heading.where(level: 1): it => {
  pagebreak(weak: true)
  v(3cm)
  align(center)[
    #context if in_body.get() [
      #text(size: 14pt, fill: rgb("#888"))[
        제 #counter(heading).display("1") 장
      ]
      #v(0.7em)
    ]
    #text(size: 26pt, weight: "bold")[#it.body]
    #v(0.6em)
    #line(length: 30%, stroke: 1pt + rgb("#1e3a8a"))
  ]
  v(2.8em)
}

// Levels 2-4: block()으로 감싸야 제목이 문단으로 취급되지 않는다
// (문단 취급 시 제목 자체와 바로 다음 문단에 first-line-indent가 붙음).
// sticky: 페이지 하단에 제목만 홀로 남는 것 방지.

// Level-2 (## section) — bold + 시각적 분리
#show heading.where(level: 2): it => {
  v(1.1em)
  block(sticky: true, text(size: 15pt, weight: "bold", fill: rgb("#1e3a8a"), it.body))
  v(0.5em)
}

// Level-3 (### sub-section) — bold + 작은 강조
#show heading.where(level: 3): it => {
  v(0.8em)
  block(sticky: true, text(size: 12.5pt, weight: "bold", it.body))
  v(0.3em)
}

// Level-4 (#### sub-sub-section) — 작은 강조
#show heading.where(level: 4): it => {
  v(0.5em)
  block(sticky: true, text(size: 11.5pt, weight: "bold", fill: rgb("#444"), it.body))
  v(0.2em)
}

// 인용 블록 — 들여쓰기 + 약간 작은 글자
#show quote.where(block: true): it => {
  v(0.4em)
  pad(left: 1.2em, right: 0.5em)[
    #set text(size: 10.5pt, style: "italic")
    #it.body
  ]
  v(0.4em)
}

// === Cover (optional, full bleed) ===

#let cover_path = "{{cover_path}}"
#if cover_path != "" [
  #set page(margin: 0pt, header: none, numbering: none)
  // fit: "cover" — 비율이 달라도 여백 없이 전면 채움
  #image(cover_path, width: 100%, height: 100%, fit: "cover")
]

// === Title page ===

#set page(margin: (x: 18mm, y: 24mm), header: none, numbering: none)
#align(center + horizon)[
  #text(size: 26pt, weight: "bold", book-title)
  #v(1em)
  #text(size: 14pt, book-author)
]
#pagebreak()

// === Table of Contents ===

#set page(numbering: "i", number-align: center, header: none)
#counter(page).update(1)
#outline(title: [차례], depth: 1, indent: auto)
#pagebreak()

// === Running header (only inside body section) ===

#set page(
  header: context {
    if in_body.get() {
      let pg = here().page()
      // 장 시작 페이지에는 헤더 생략 (outline 제목 heading이 잡히는 것도 함께 차단)
      let opener = query(heading.where(level: 1)).filter(h => h.location().page() == pg)
      let chapters = query(heading.where(level: 1).before(here()))
      if opener.len() == 0 and chapters.len() > 0 {
        let chap = chapters.last()
        set text(size: 9pt, fill: rgb("#666"))
        if calc.even(pg) [
          #emph(book-title) #h(1fr)
        ] else [
          #h(1fr) #emph[#chap.body]
        ]
      }
    }
  },
)

// === Body (frontmatter + body + backmatter, role-aware) ===

{{body}}
