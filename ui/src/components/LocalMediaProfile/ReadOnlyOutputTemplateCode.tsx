import CodeMirror from '@uiw/react-codemirror'
import {EditorView} from '@codemirror/view'

import {keepExpressionsTogether, markPathSlashes, outputTemplateSyntaxExtensions} from './outputTemplateCodeMirror'
import {
    parseOutputTemplate,
    renderCompactOutputTemplate,
    renderEditorOutputTemplate,
    renderPathOutputTemplate,
    type OutputTemplateSourceMode,
} from './outputTemplateFormatting'
import './OutputTemplateEditor.css'
import './ReadOnlyOutputTemplateCode.css'

// 'path' hides set blocks, logic tags and comments and shows only the path with its variables.
// 'simplified-path' also shows each expression as just its first variable, without filters or fallbacks.
export type OutputTemplateRenderMode = 'compact' | 'editor' | 'path' | 'simplified-path'

export type ReadOnlyOutputTemplateCodeProps = {
    source: string
    label: string
    sourceMode?: OutputTemplateSourceMode
    renderMode?: OutputTemplateRenderMode
    className?: string
}

const readOnlyCodeExtensions = [
    ...outputTemplateSyntaxExtensions,
    EditorView.lineWrapping,
    keepExpressionsTogether,
]

const pathCodeExtensions = [
    ...readOnlyCodeExtensions,
    markPathSlashes,
]

export default function ReadOnlyOutputTemplateCode({
    source,
    label,
    sourceMode = 'editor',
    renderMode = 'editor',
    className,
}: ReadOnlyOutputTemplateCodeProps) {
    const ast = parseOutputTemplate(source, sourceMode)
    const isPath = renderMode === 'path' || renderMode === 'simplified-path'
    const value = renderMode === 'compact'
        ? renderCompactOutputTemplate(ast)
        : isPath
            ? renderPathOutputTemplate(ast, {simplifyExpressions: renderMode === 'simplified-path'})
            : renderEditorOutputTemplate(ast).value

    return (
        <CodeMirror
            className={`output-template-code-editor read-only-output-template-code-editor${isPath ? ' is-path' : ''}${className ? ` ${className}` : ''}`}
            value={value}
            editable={false}
            extensions={isPath ? pathCodeExtensions : readOnlyCodeExtensions}
            basicSetup={{
                lineNumbers: false,
                foldGutter: false,
                highlightActiveLine: false,
                highlightActiveLineGutter: false,
                autocompletion: false,
            }}
            aria-label={label}
        />
    )
}
