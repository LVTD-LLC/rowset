package main

import (
	"context"
	"fmt"
	"os"

	"github.com/LVTD-LLC/rowset/cli/internal/rowsetcli"
)

func main() {
	if err := rowsetcli.Run(context.Background(), rowsetcli.IO{
		Stdin:  os.Stdin,
		Stdout: os.Stdout,
		Stderr: os.Stderr,
	}, os.Args[1:]); err != nil {
		_, _ = fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
