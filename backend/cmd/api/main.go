// Command api is the CurbOS backend entrypoint.
//
// PR-01 intentionally provides only a compilable foundation. Operational HTTP
// endpoints and database readiness checks are introduced in later M1 slices.
package main

import (
	"fmt"
	"io"
	"os"
)

const foundationMessage = "CurbOS API foundation: no HTTP endpoints are implemented in PR-01."

func run(output io.Writer) error {
	_, err := fmt.Fprintln(output, foundationMessage)
	return err
}

func main() {
	if err := run(os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, "write startup message:", err)
		os.Exit(1)
	}
}
