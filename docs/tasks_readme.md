
## Tasks

`tasks` analyzes Markdown file and visualizes the result.

```
tasks [filename]
```

- filename: filename to analyze. Default is tasks.md.

### format

```
# GROUP Active Task list

## RSPN Tax filling
  DUE: <2026-05-07 Thu>
  <2026-04-24 Fri> I submit foam.

## ACTIVE Buy coffee
  DUE: <2026-05-03 Sun>
  Looking for great coffee
```

You can put status string at the top of heading.

- `GROUP` : Indicates the start of task group
- `ACTIVE` : Indicates that the task needs your action
- `RSPN` : Indicates that the task is waiting on someone.
- `DONE` : The task is completed.



