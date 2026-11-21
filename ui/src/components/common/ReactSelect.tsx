import Select, {type GroupBase, type Props} from 'react-select'
import {useDialogMenuProps} from '../Modal/dialogMenus'

/** react-select's Select, whose menu opens on top of the page when it sits in a scrolling dialog. */
export default function ReactSelect<
    Option,
    IsMulti extends boolean = false,
    Group extends GroupBase<Option> = GroupBase<Option>,
>(props: Props<Option, IsMulti, Group>) {
    const dialogMenuProps = useDialogMenuProps()
    return <Select<Option, IsMulti, Group> {...dialogMenuProps} {...props} styles={{...dialogMenuProps.styles, ...props.styles}}/>
}
