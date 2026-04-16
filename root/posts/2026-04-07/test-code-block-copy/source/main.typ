#let title = "Test Code Block Copy"

#let content = [
  Since this is a programmer's blog, posts will inevitably contain code. When Typst renders those snippets as SVG images, however, the visible text is no longer directly copyable. A determined reader could still open the browser's developer tools, inspect the `<div class="sr-only">`, and recover the source, but that is clearly not a user-friendly workflow.

  After some experimentation, I found that Typst's `query` command makes it straightforward to extract the raw text of each `raw` element. The build script can then attach copy targets, and a small bit of JavaScript can write the original source straight to the clipboard.

  To try it out, click any inline code snippet above or the code block below to copy the exact source text to your clipboard:

  ```hs
  -- This is a code block example
  greet :: String -> IO ()
  greet name = putStrLn ("Hello, " ++ name ++ "!")
  ```

  The PDF version does not include the JavaScript copy hook, but it also does not need one: the text in the PDF is directly selectable.

  The functionality does not apply to sr-only text for the same reason. However, if you navigate to the very end of the plain text with a screen reader, you may eventually reach the SVG object and interact with the copy links inside.
]

#if sys.inputs.at("with_driver", default: "false") == "false" {
  import "../../driver/template.typ": article
  show: article.with(title: title)
  content
}
