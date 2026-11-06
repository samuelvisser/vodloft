import {HighlightStyle, syntaxHighlighting} from '@codemirror/language'
import {Prec, type Extension} from '@codemirror/state'
import {Decoration, EditorView, MatchDecorator, ViewPlugin, type DecorationSet, type ViewUpdate} from '@codemirror/view'
import {jinja} from '@codemirror/lang-jinja'
import {tags} from '@lezer/highlight'

export const outputTemplateHighlightStyle = HighlightStyle.define([
    {tag: tags.brace, class: 'cm-jinja-brace'},
    {
        tag: [tags.keyword, tags.controlKeyword, tags.definitionKeyword, tags.operatorKeyword, tags.logicOperator],
        class: 'cm-jinja-keyword',
    },
    {
        tag: [tags.variableName, tags.propertyName, tags.special(tags.variableName)],
        class: 'cm-jinja-variable',
    },
    {tag: tags.string, class: 'cm-jinja-string'},
    {tag: [tags.number, tags.bool], class: 'cm-jinja-literal'},
    {
        tag: [tags.operator, tags.arithmeticOperator, tags.compareOperator],
        class: 'cm-jinja-operator',
    },
    {tag: tags.comment, class: 'cm-jinja-comment'},
    {tag: tags.blockComment, class: 'cm-jinja-comment'},
])

export const outputTemplateSyntaxExtensions = [
    jinja(),
    syntaxHighlighting(outputTemplateHighlightStyle),
]

// Marks each `{{ … }}` so a wrapped read-only template never splits a variable across lines. The spaces
// stay ordinary spaces, because the Jinja highlighter does not read a non-breaking space as whitespace.
const expressionMatcher = new MatchDecorator({
    regexp: /\{\{.*?\}\}/g,
    decoration: Decoration.mark({class: 'cm-jinja-expression'}),
})

export const keepExpressionsTogether = ViewPlugin.fromClass(class {
    decorations: DecorationSet

    constructor(view: EditorView) {
        this.decorations = expressionMatcher.createDeco(view)
    }

    update(update: ViewUpdate) {
        this.decorations = expressionMatcher.updateDeco(update, this.decorations)
    }
}, {decorations: (plugin) => plugin.decorations})

// For a path view: marks the slashes between folders, outside any `{{ … }}`, so they can stand out, and
// marks each path section (a slash up to the next one) so a wrapped path only breaks before a slash.
const pathSlashMark = Decoration.mark({class: 'cm-path-slash'})
const pathSectionMark = Decoration.mark({class: 'cm-path-section'})
const pathSlashMatcher = new MatchDecorator({
    regexp: /\{\{.*?\}\}|\//g,
    decorate: (add, from, to, match) => {
        if (match[0] === '/') add(from, to, pathSlashMark)
    },
})
const pathSectionMatcher = new MatchDecorator({
    // Text before the first slash, or a slash with everything up to the next slash outside a variable.
    regexp: /\/?(?:\{\{.*?\}\}|\{(?!\{)|[^/{])+|\//g,
    decoration: pathSectionMark,
})

function matcherPlugin(matcher: MatchDecorator) {
    return ViewPlugin.fromClass(class {
        decorations: DecorationSet

        constructor(view: EditorView) {
            this.decorations = matcher.createDeco(view)
        }

        update(update: ViewUpdate) {
            this.decorations = matcher.updateDeco(update, this.decorations)
        }
    }, {decorations: (plugin) => plugin.decorations})
}

// The section mark has the lowest precedence, so it wraps the slash and variable marks instead of being
// split by them.
export const markPathSlashes: Extension = [
    matcherPlugin(pathSlashMatcher),
    Prec.lowest(matcherPlugin(pathSectionMatcher)),
]
