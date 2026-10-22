/* Qt returns an implicitly shared list. Balance its reference atomically.
 * No Qt headers, CRT, process hooks or initialization code are needed.
 */
__declspec(dllexport) int mmd_atomic_deref(volatile int *reference)
{
    return __atomic_sub_fetch(reference, 1, __ATOMIC_ACQ_REL);
}
