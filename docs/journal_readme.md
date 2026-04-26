
# Journal

`journal` is an application to display achievement list and graphs from your journal Markdown file.

## Usage

The default filename is `journal.md`

```
journal [filename] 
```

`r`: Reload chart
Up and Down: Move to previous or next month
Left or Right: Change graph
mouse : Show date indicator
'q': Quit

## Markdown Syntax

The application recognizes the following syntax to convert them to achievement chart, or graph.

Here is am example of journaling Markdown file:

```
## <2026-04-08 Wed>

- [X] Running
- [ ] Feed water to plants
- [170] Weight
- [8:00] Wake Up

It was a nice day for running.
You can write anything here.

## <2026-04-09 Thu>

- [X] Running
- [X] Feed water to plants
- [169] Weight
- [7:40] Wake Up

```

The script expects One journal file has multiple entries.

### Date

Header with date recognizes as a journal entry.
The date format is <yyyy-mm-dd>. `analog_clock` has a feature to copy date to clipboard.

Date order can be both (Recent entry is the top of the file, or the last of the file)

### Achievement chart

When you write a list with a checkbox, it appears as an Achievement chart. For example:

```
  - [X] Running
```

Optionally you can fill multiple entries for past dates. The following example fills today and last two days.

```
 - [X,X,X] gym
```


### Graph

If you put number in the checkbox, it appears as a graph. The number can be time.

```
  - [170.0] Weight
  - [22:00] Time to sleep
```


