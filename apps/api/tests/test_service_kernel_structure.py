import inspect


def test_row_mutation_helpers_live_outside_service_kernel():
    from apps.api import row_mutations

    assert inspect.getmodule(row_mutations.create_dataset_row) is row_mutations
    assert inspect.getmodule(row_mutations.patch_dataset_row) is row_mutations
    assert inspect.getmodule(row_mutations.delete_dataset_row) is row_mutations
    assert inspect.getmodule(row_mutations.delete_dataset_rows) is row_mutations
