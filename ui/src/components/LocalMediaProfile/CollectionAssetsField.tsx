import {Controller, type UseFormReturn} from 'react-hook-form'
import type {LocalMediaProfilePreviewState} from '../../lib/localMediaProfilePreview'
import ReadMore from "../../utils/ReadMore";
import {createSelectRegistry} from "../../utils/selectRegistry";
import SimpleSelect from "../common/SimpleSelect";

export default function CollectionAssetsField({form, preview}: {
    form: UseFormReturn<any>
    preview: LocalMediaProfilePreviewState
}) {
    const {control, formState: {errors}} = form
    const root = preview.result?.collectionRoot
    const collectionAssetsReg = createSelectRegistry('CollectionAssetsMode', {
        system: {label: root ? `System (${root.systemEnabled ? 'enabled' : 'disabled'})` : 'System'},
        enabled: {label: 'Enabled'},
        disabled: {label: 'Disabled'},
    })
    const fieldError = errors.downloadCollectionAssets
    const collectionRootSummary = preview.error
        ? preview.error
        : preview.simulatingCustomIndexes
            ? 'Calculating simulated Custom Index… This preview needs to recalculate index assignments and may take longer than normal.'
            : root?.path
                ? root.path
                : root?.reason
                    ? root.reason
                    : preview.loading
                        ? 'Resolving collection root...'
                        : 'Select an episode and enter an output template to preview the shared collection root.'


    return (
        <div className="form-row">
            <label htmlFor="mp-collection-assets">Download collection images</label>
            <Controller
                control={control}
                name="downloadCollectionAssets"
                render={({field}) => (
                    <SimpleSelect
                        inputId="mp-collection-assets"
                        ref={field.ref}
                        name={field.name}
                        registry={collectionAssetsReg}
                        value={field.value == null ? 'system' : field.value ? 'enabled' : 'disabled'}
                        onChange={(value) => field.onChange(value === 'enabled' ? true : value === 'disabled' ? false : null)}
                        onBlur={field.onBlur}
                        aria-invalid={!!fieldError}
                        aria-describedby={`mp-collection-assets-help${fieldError ? ' mp-collection-assets-error' : ''}`}
                    />
                )}
            />
            {fieldError && <div id="mp-collection-assets-error" className="error" role="alert">{String(fieldError.message)}</div>}
            <div id="mp-collection-assets-help" className="help">
                <ReadMore summary={<>
                    Save collection assets to collection root: <code style={{overflowWrap: 'anywhere'}}>{collectionRootSummary}</code>
                </>}>
                    <p>
                        Save available poster, background and square artwork in the collection root folder. This
                        is particularly useful if you consume the collection through a media server.
                    </p>
                    <p>
                        <strong>System</strong> follows the current system-wide default shown in parentheses.
                    </p>
                    <p>
                        <strong>Enabled</strong> downloads collection assets to collection root folder.
                    </p>
                    <p>
                        <strong>Disabled</strong> does not download collection assets.
                    </p>
                    <p>
                        Existing custom artwork is preserved.
                    </p>
                    <p>
                        VODLoft dynamically tries to resolve the root folder for your collection. This resolver is very powerful
                        and takes into account even conditional Jinja paths. To make sure VODLoft actually finds your collection
                        root folder correctly, select any episode in the 'Example episode' picker below, and the path above will automatically
                        show you what VODLoft resolved as your collection root, without changing any files or saving anything yet.
                    </p>
                    <p>
                        If the collection root VODLoft found is not correct, this is likely due to an ambiguous path in your output
                        template. Please review it below.
                    </p>
                </ReadMore>
            </div>
        </div>
    )
}
